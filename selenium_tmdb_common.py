"""Code shared by selenium-tmdb-wikidata_id-v2.py and selenium-tmdb-deathday-v2.py.

The helpers both notebooks carry in their identical helper cell, minus what only
the wikidata_id robot uses, which stays in its script. Compared with the
notebooks, Chrome is a real one on a persistent profile (see launch_chrome) and
the %store cursor is read without IPython (see set_store_value).

The scripts load it with `from selenium_tmdb_common import *`, so their code
reads as in the notebooks. A module global they need to change (LOG_BASENAME)
is set on the module itself: `selenium_tmdb_common.LOG_BASENAME = ...`.
Paths (.env, data/, logs/) are relative: the scripts move to the repository
folder before importing this file.
"""

# =============================================================================
# Imports (notebook cell 1)
# =============================================================================
import base64
import getpass
import hashlib
import json
import os
import posixpath
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import paramiko
import urllib3
from dotenv import load_dotenv
from IPython import get_ipython
from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    InvalidElementStateException,
    InvalidSessionIdException,
    NoSuchElementException,
    NoSuchWindowException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
import shutil
import subprocess
import urllib.request

# =============================================================================
# Console: Quick Edit off
# =============================================================================
def disable_console_quick_edit():
    """Turn off Quick Edit in the Windows console the script runs in.

    With Quick Edit on, a click in the window starts a selection, and the script then
    freezes at its next print until Esc is pressed: a run sat 10 minutes on Vija Vetra
    that way on 2026-11-09. It cannot be done from the .bat launchers, cmd.exe puts
    the console mode back after every program it runs; set here, it holds for as long
    as the script lives. Does nothing outside a Windows console (Windows Terminal has
    no Quick Edit, a redirected stdin has no console mode).
    """
    if os.name != 'nt':
        return
    try:
        import ctypes
        import ctypes.wintypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-10)          # STD_INPUT_HANDLE
        mode = ctypes.wintypes.DWORD()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            # clear ENABLE_QUICK_EDIT_MODE (0x40), keep ENABLE_EXTENDED_FLAGS (0x80) so it applies
            kernel32.SetConsoleMode(handle, (mode.value & ~0x0040) | 0x0080)
    except Exception:
        pass


disable_console_quick_edit()


# =============================================================================
# Configuration from .env (notebook cell 2)
# =============================================================================
load_dotenv(dotenv_path=Path('.env'), override=True)

sftp_host = os.getenv('SFTP_HOST')
sftp_port = int(os.getenv('SFTP_PORT') or 22)
sftp_login = os.getenv('SFTP_LOGIN')
sftp_host_key_fingerprint = os.getenv('SFTP_SSHHOSTKEYFINGERPRINT')
sftp_key_path = os.getenv('SFTP_KEY')
sftp_key_passphrase = os.getenv('SFTP_KEY_PASSPHRASE')
sftp_password = os.getenv('SFTP_PASSWORD')
sftp_base_folder = os.getenv('SFTP_FOLDER')
tmdb_login = os.getenv('TMDB_LOGIN')
tmdb_password = os.getenv('TMDB_PASSWORD')

# SFTP_PASSWORD is optional now: the connection authenticates with an SSH key
# first (SFTP_LOGIN + SFTP_SSHHOSTKEYFINGERPRINT) and only falls back to the
# password when one is present in the .env.
if not sftp_host or not sftp_login or not sftp_base_folder:
    raise ValueError('Missing SFTP configuration in .env: SFTP_HOST, SFTP_LOGIN, SFTP_FOLDER')

if not tmdb_login or not tmdb_password:
    raise ValueError('Missing TMDB configuration in .env: TMDB_LOGIN, TMDB_PASSWORD')

# =============================================================================
# Shared helpers (notebook helper cell, v2 Chrome)
# =============================================================================
SAVE_BUTTON_XPATH = '//input[@value="Save"]'

# TMDB's cookie banner is OneTrust, injected after the page loads and anchored at
# the bottom of the window, which is where the Save button of an edit page sits:
# while it is up, a click aimed at Save lands on the banner instead. 'Tout
# refuser' is #onetrust-reject-all-handler, and declining sets
# OptanonAlertBoxClosed for the profile, so it has to be done once per browser,
# which means once per restart too.
COOKIE_BANNER_ID = 'onetrust-banner-sdk'
COOKIE_DECLINE_ID = 'onetrust-reject-all-handler'
COOKIE_BANNER_TIMEOUT = 10

# Chrome dies on long runs: a crashed tab, a renderer out of memory, a driver
# that stops answering. These bounds decide how fast the loop notices, and how
# it tells a dead browser from a slow page. PAGE_LOAD_TIMEOUT stays below
# HTTP_CLIENT_TIMEOUT on purpose, so a slow page raises TimeoutException from
# chromedriver instead of a client read timeout that looks like a crash.
HTTP_CLIENT_TIMEOUT = 60
PAGE_LOAD_TIMEOUT = 45
SCRIPT_TIMEOUT = 30
BROWSER_QUIT_TIMEOUT = 15
BROWSER_RESTART_ATTEMPTS = 3
LOGIN_CONFIRM_TIMEOUT = 120

# Every TMDB page is same-site, so Chrome serves the whole run from a single
# renderer whose memory only grows: measured over 12 navigations, 16 MB per page
# as Chrome is launched by default, 9 MB with the back/forward cache off. Nothing
# reclaims all of it, so the browser is recycled every BROWSER_RECYCLE_EVERY
# records. Raise it if the extra logins are a nuisance, set it to 0 to turn
# recycling off.
#
# No CDP memory purge between records any more: since Chrome 154 (2026-10-08),
# Memory.forciblyPurgeJavaScriptMemory leaves every later navigation hanging.
# The page draws, but chromedriver never sees the load end, so each record cost
# three 45 s timeouts and was skipped, the cursor moving on regardless.
BROWSER_RECYCLE_EVERY = 250

# A record that writes nothing is normal (locked field, 404); a run of them is
# not. Over the 1061 records of the previous run, 1046 were written and the
# longest run without a write was 1, so a streak this long means the browser or
# TMDB stopped cooperating and the loop must not keep marking records done.
MAX_CONSECUTIVE_SKIPS = 8

# chromedriver reports a lost browser in the message rather than in the exception
# type, so the wording is what gets matched.
BROWSER_GONE_MESSAGES = (
    'invalid session id',
    'no such session',
    'session deleted',
    'chrome not reachable',
    'disconnected',
    'target crashed',
    'tab crashed',
    'unable to connect to renderer',
    'not connected to devtools',
    'failed to connect',
)


class BrowserSessionLost(RuntimeError):
    """Chrome, chromedriver or the TMDB session is gone: the row needs a new browser."""


SSH_CONFIG_PATH = Path.home() / '.ssh' / 'config'


class HostKeyVerificationError(paramiko.SSHException):
    """The SFTP server host key does not match SFTP_SSHHOSTKEYFINGERPRINT."""


def parse_host_key_fingerprint(raw_fingerprint):
    """Split a WinSCP-style fingerprint into (key_type, algorithm, digest).

    The key type and the bit count are optional, so the same .env value can be
    shared with the WinSCP/PowerShell scripts. Accepted shapes:
        ssh-ed25519 256 SHA256:<base64>
        ssh-ed25519 256 <base64>
        SHA256:<base64>
        ssh-rsa 2048 aa:bb:...:ff      (MD5)
    """
    tokens = raw_fingerprint.strip().split()
    if not tokens:
        raise ValueError('SFTP_SSHHOSTKEYFINGERPRINT is empty')

    key_type = tokens[0] if len(tokens) > 1 else None
    digest = tokens[-1]

    if digest.upper().startswith('SHA256:'):
        return key_type, 'sha256', digest[len('SHA256:'):].rstrip('=')
    if digest.upper().startswith('MD5:'):
        digest = digest[len('MD5:'):]
    if ':' in digest:
        return key_type, 'md5', digest.replace(':', '').lower()
    return key_type, 'sha256', digest.rstrip('=')


def compute_host_key_digest(host_key, algorithm):
    if algorithm == 'md5':
        return hashlib.md5(host_key.asbytes()).hexdigest()
    return base64.b64encode(hashlib.sha256(host_key.asbytes()).digest()).decode('ascii').rstrip('=')


class FingerprintHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """Pin the server to SFTP_SSHHOSTKEYFINGERPRINT instead of known_hosts.

    Same contract as WinSCP's SessionOptions.SshHostKeyFingerprint.
    """

    def __init__(self, raw_fingerprint):
        self.key_type, self.algorithm, self.digest = parse_host_key_fingerprint(raw_fingerprint)

    def missing_host_key(self, client, hostname, key):
        if self.key_type and key.get_name() != self.key_type:
            raise HostKeyVerificationError(
                f'SSH host key type mismatch: the server offered {key.get_name()}, '
                f'SFTP_SSHHOSTKEYFINGERPRINT declares {self.key_type}.'
            )

        actual_digest = compute_host_key_digest(key, self.algorithm)
        if actual_digest != self.digest:
            raise HostKeyVerificationError(
                f'SSH host key fingerprint mismatch ({self.algorithm}): the server presented '
                f'{actual_digest}, SFTP_SSHHOSTKEYFINGERPRINT expects {self.digest}. '
                'Refusing to connect.'
            )


def collect_private_key_files():
    """Private keys to offer, most specific first.

    paramiko only auto-discovers the default ~/.ssh/id_rsa|id_ecdsa|id_ed25519
    names, so the ~/.ssh/config lookup is what makes a per-host key such as
    id_ed25519_<vps> usable. 'IdentitiesOnly yes' is honoured so the server is
    not offered every key on the machine (MaxAuthTries).
    """
    if sftp_key_path:
        return [str(Path(sftp_key_path).expanduser())]

    candidates = []
    identities_only = False

    if SSH_CONFIG_PATH.is_file():
        ssh_config = paramiko.SSHConfig()
        with SSH_CONFIG_PATH.open(encoding='utf-8') as config_file:
            ssh_config.parse(config_file)
        host_config = ssh_config.lookup(sftp_host)
        identities_only = str(host_config.get('identitiesonly', 'no')).lower() in ('yes', 'true')
        candidates.extend(Path(name).expanduser() for name in host_config.get('identityfile', []))

    if not (identities_only and candidates):
        ssh_dir = Path.home() / '.ssh'
        if ssh_dir.is_dir():
            candidates.extend(sorted(ssh_dir.glob('id_*')))

    key_files = []
    for candidate in candidates:
        if candidate.suffix == '.pub' or not candidate.is_file():
            continue
        if str(candidate) not in key_files:
            key_files.append(str(candidate))
    return key_files


def is_encrypted_private_key(key_file):
    for key_class in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            key_class.from_private_key_file(key_file)
            return False
        except paramiko.PasswordRequiredException:
            return True
        except Exception:
            continue
    return False


KEY_PASSPHRASE_CACHE = {}


def resolve_key_passphrase(key_files):
    """SFTP_KEY_PASSPHRASE when set, otherwise ask once for a protected key.

    Prompting keeps the passphrase out of the .env and out of the notebook
    output; the answer is cached so a run over the three datasets only asks
    once. Clear KEY_PASSPHRASE_CACHE to be prompted again.
    """
    if sftp_key_passphrase:
        return sftp_key_passphrase

    if 'passphrase' in KEY_PASSPHRASE_CACHE:
        return KEY_PASSPHRASE_CACHE['passphrase']

    if not any(is_encrypted_private_key(key_file) for key_file in key_files):
        return None

    if get_ipython() is None and not sys.stdin.isatty():
        return None

    KEY_PASSPHRASE_CACHE['passphrase'] = getpass.getpass(
        'Passphrase for the SSH private key (empty to skip key auth): '
    ) or None
    return KEY_PASSPHRASE_CACHE['passphrase']


def make_transport_factory():
    """Negotiate the host key type declared in SFTP_SSHHOSTKEYFINGERPRINT first.

    Without known_hosts entries paramiko would otherwise pick its own preferred
    algorithm, which may not be the one the fingerprint was taken from.
    """
    key_type = parse_host_key_fingerprint(sftp_host_key_fingerprint)[0] if sftp_host_key_fingerprint else None

    def transport_factory(sock, *args, **kwargs):
        transport = paramiko.Transport(sock, *args, **kwargs)
        options = transport.get_security_options()
        if key_type and key_type in options.key_types:
            options.key_types = [key_type] + [k for k in options.key_types if k != key_type]
        return transport

    return transport_factory


def build_ssh_client():
    client = paramiko.SSHClient()
    if sftp_host_key_fingerprint:
        client.set_missing_host_key_policy(FingerprintHostKeyPolicy(sftp_host_key_fingerprint))
    else:
        print('WARNING: SFTP_SSHHOSTKEYFINGERPRINT is not set, falling back to ~/.ssh/known_hosts.')
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    return client


def open_sftp_connection():
    """Open an SFTP session on SFTP_HOST as SFTP_LOGIN.

    First choice: SSH public-key authentication, with the server pinned to
    SFTP_SSHHOSTKEYFINGERPRINT. Second choice: the historical SFTP_PASSWORD.
    A host key mismatch is never retried - it aborts the connection.
    """
    key_files = collect_private_key_files()
    attempts = [(
        'SSH key',
        {
            'key_filename': key_files or None,
            'passphrase': resolve_key_passphrase(key_files),
            'allow_agent': True,
            'look_for_keys': True,
        },
    )]
    if sftp_password:
        attempts.append((
            'password',
            {'password': sftp_password, 'allow_agent': False, 'look_for_keys': False},
        ))

    common_kwargs = {
        'hostname': sftp_host,
        'port': sftp_port,
        'username': sftp_login,
        'timeout': 30,
        'transport_factory': make_transport_factory(),
    }

    last_error = None
    for label, auth_kwargs in attempts:
        client = build_ssh_client()
        try:
            client.connect(**common_kwargs, **auth_kwargs)
        except (HostKeyVerificationError, paramiko.BadHostKeyException):
            client.close()
            raise
        except (paramiko.AuthenticationException, paramiko.SSHException) as exc:
            client.close()
            print(f'SFTP {label} authentication failed: {type(exc).__name__}: {exc}')
            last_error = exc
            continue

        print(f'SFTP connected using {label} authentication')
        return client, client.open_sftp()

    raise last_error or paramiko.AuthenticationException('No SFTP authentication method succeeded')


def download_new_csv_files(remote_folder, local_folder):
    remote_path = posixpath.join(sftp_base_folder, remote_folder)
    local_path = Path('./data') / local_folder
    local_path.mkdir(parents=True, exist_ok=True)

    downloaded_count = 0
    skipped_count = 0

    ssh_client, sftp = open_sftp_connection()

    try:
        for entry in sftp.listdir_attr(remote_path):
            if entry.filename in ('.', '..'):
                continue

            remote_file = posixpath.join(remote_path, entry.filename)
            local_file = local_path / entry.filename

            try:
                if (entry.st_mode & 0o170000) == 0o040000:
                    continue
            except Exception:
                pass

            if local_file.exists():
                skipped_count += 1
                continue

            sftp.get(remote_file, str(local_file))
            downloaded_count += 1
    finally:
        sftp.close()
        ssh_client.close()

    print(f'SFTP folder: {remote_path}')
    print(f'Local folder: {local_path.resolve()}')
    print(f'Downloaded {downloaded_count} new file(s), skipped {skipped_count} existing file(s)')


def get_latest_csv(local_folder, local_file_basename):
    base_candidates = [Path('./data') / local_folder, Path('./data')]

    csv_candidates = []
    for base in base_candidates:
        if base.exists():
            csv_candidates.extend(base.glob(local_file_basename + '*.csv'))

    if not csv_candidates:
        raise FileNotFoundError(
            'No file found matching ' + local_file_basename + '*.csv in ./data or ./data/<local_folder>'
        )

    # The export date lives in the filename; mtime is only the SFTP download
    # time, identical across a whole mirror pass, so it cannot order the exports.
    latest_csv = max(csv_candidates, key=lambda p: (p.name, str(p)))
    print(f'Using latest CSV: {latest_csv}')
    return latest_csv

# The notebooks persist the resume cursor with the IPython %store magic, through
# get_ipython(), which is None outside Jupyter. These read and write the very
# database %store uses (<IPython dir>/profile_default/db, keys
# 'autorestore/<name>'), so notebooks and scripts share their cursors.


def open_store_db():
    try:
        from IPython.external.pickleshare import PickleShareDB
    except ImportError:  # IPython older than 9 depends on the pickleshare package
        from pickleshare import PickleShareDB
    from IPython.paths import get_ipython_dir

    return PickleShareDB(os.path.join(get_ipython_dir(), 'profile_default', 'db'))


def set_store_value(store_key, value):
    open_store_db()['autorestore/' + store_key] = value


def get_store_value(store_key, default=0):
    try:
        return open_store_db()['autorestore/' + store_key]
    except KeyError:
        return default


def apply_http_client_timeout(driver, timeout=HTTP_CLIENT_TIMEOUT):
    """Shorten the read timeout of the HTTP connection to chromedriver.

    ChromiumRemoteConnection hard-codes 120 s and webdriver.Chrome takes no
    client_config, so the value is set on the live connection: selenium passes
    client_config.timeout on every request, so it applies from the next command
    on. Without it a crashed Chrome only surfaces two minutes later, as a raw
    urllib3 ReadTimeoutError.
    """
    try:
        driver.command_executor.client_config.timeout = timeout
    except AttributeError as exc:
        print(f'Could not shorten the chromedriver HTTP timeout ({exc}).')

# ---------------------------------------------------------------------------
# A real Chrome instead of a disposable one (v2).
#
# The notebooks let chromedriver start a fresh Chrome on an empty profile: every
# run, and every restart, logs in again with the .env credentials. The v2 scripts
# start Chrome themselves, as a person would (no --enable-automation flag), on a
# profile that persists between runs, and Selenium attaches to it through the
# DevTools port. The TMDB session and the declined cookie banner survive in that
# profile, so a login is needed only when TMDB ends the session.
#
# It cannot be the everyday Chrome profile: since Chrome 136 the DevTools port is
# refused on the default user data directory. CHROME_PROFILE_DIR is a separate
# directory, logged in to TMDB once by hand, and the profile's only user is the
# robot. While it is open, any local program can drive it through the port, which
# listens on 127.0.0.1 only.
# ---------------------------------------------------------------------------
CHROME_DEBUG_PORT = int(os.getenv('CHROME_DEBUG_PORT') or 9222)
CHROME_PROFILE_DIR = Path(
    os.getenv('CHROME_PROFILE_DIR')
    or Path(os.getenv('LOCALAPPDATA') or Path.home()) / 'selenium-tmdb' / 'chrome-profile'
)
CHROME_BINARY = os.getenv('CHROME_BINARY')
CHROME_START_TIMEOUT = 30
LOGIN_MANUAL_TIMEOUT = 600

# An edit page redirects to /login when the session is gone, which is what the
# notebooks already rely on (BrowserSessionLost). Opening it writes nothing.
SESSION_CHECK_URL = 'https://www.themoviedb.org/movie/550/edit?active_nav_item=external_ids'

# The Chrome this process launched, None when it attached to one already open.
CHROME_PROCESS = None


def find_chrome_binary():
    if CHROME_BINARY:
        return CHROME_BINARY

    candidates = [
        Path(os.environ[variable]) / 'Google' / 'Chrome' / 'Application' / 'chrome.exe'
        for variable in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA')
        if os.environ.get(variable)
    ]
    candidates.append(Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    for name in ('google-chrome', 'google-chrome-stable', 'chromium', 'chrome'):
        found = shutil.which(name)
        if found:
            return found

    raise FileNotFoundError('Chrome not found: set CHROME_BINARY in .env.')


def is_chrome_listening():
    """True when a Chrome answers on the DevTools port.

    The request bypasses any system proxy: a VPN or corporate proxy must not
    see, or swallow, a request to 127.0.0.1.
    """
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f'http://127.0.0.1:{CHROME_DEBUG_PORT}/json/version', timeout=2) as response:
            return response.status == 200
    except OSError:
        return False


def launch_chrome():
    """Start Chrome on CHROME_PROFILE_DIR with the DevTools port, unless one already listens.

    Chrome runs in its own process group, so a Ctrl+C in the terminal stops the
    script without killing the browser, and it outlives the script like the
    window left open after a notebook run.
    """
    global CHROME_PROCESS

    if is_chrome_listening():
        print(f'Attaching to the Chrome already listening on port {CHROME_DEBUG_PORT}.')
        return

    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        find_chrome_binary(),
        f'--remote-debugging-port={CHROME_DEBUG_PORT}',
        f'--user-data-dir={CHROME_PROFILE_DIR}',
        # Moved here from build_chrome_options: with an attached Selenium, the
        # flags have to be on Chrome's own command line.
        '--disable-features=BackForwardCache',
        '--no-first-run',
        '--no-default-browser-check',
        'about:blank',
    ]
    popen_options = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
    if os.name == 'nt':
        popen_options['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        popen_options['start_new_session'] = True
    CHROME_PROCESS = subprocess.Popen(command, **popen_options)

    deadline = time.time() + CHROME_START_TIMEOUT
    while time.time() < deadline:
        if is_chrome_listening():
            print(f'Chrome started on {CHROME_PROFILE_DIR} (port {CHROME_DEBUG_PORT}).')
            return
        time.sleep(0.5)

    raise RuntimeError(
        f'Chrome does not answer on port {CHROME_DEBUG_PORT}. If a Chrome window is already open '
        f'on {CHROME_PROFILE_DIR} without that port, close it and run again.'
    )


def build_chrome_options():
    """Options that attach Selenium to the Chrome launch_chrome() started.

    Launch flags have no effect on an attached session: they live in launch_chrome().
    """
    options = webdriver.ChromeOptions()
    options.debugger_address = f'127.0.0.1:{CHROME_DEBUG_PORT}'
    return options


def init_driver():
    launch_chrome()
    driver = webdriver.Chrome(
        service=ChromeService(ChromeDriverManager().install()),
        options=build_chrome_options()
    )
    # Attached, chromedriver may pick one of Chrome's own UI views (Chrome 156:
    # chrome://omnibox-popup), which vanishes and fails the first command with
    # 'no such window'. window_handles lists real tabs only.
    handles = driver.window_handles
    if handles:
        driver.switch_to.window(handles[0])
    else:
        driver.switch_to.new_window('tab')
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    driver.set_script_timeout(SCRIPT_TIMEOUT)
    apply_http_client_timeout(driver)
    return driver


def get_chrome_error_code(driver):
    """Return Chrome's error code when the page shown is Chrome's own error page.

    This is the failure that goes unnoticed: after a renderer runs out of memory
    Chrome replaces the page with its 'Aw, Snap!' document, served by the browser
    itself. driver.get() returns, every command keeps working, nothing raises,
    and a loop that does not look for it skips record after record convinced it
    saw a page. driver.current_url still reports the URL that was asked for, so
    document.URL is what gives it away (chrome-error://chromewebdata/), together
    with the neterror body class and the error code the page displays.
    """
    try:
        state = driver.execute_script(
            'return [document.URL, document.body ? document.body.className : ""];'
        )
    except WebDriverException:
        return None

    if not state:
        return None

    document_url = state[0] or ''
    body_class = state[1] or ''
    if not document_url.startswith('chrome-error://') and 'neterror' not in body_class:
        return None

    codes = driver.find_elements(By.CSS_SELECTOR, 'div.error-code')
    return codes[0].text.strip() if codes else 'unknown'


def open_page(driver, url):
    """Navigate to url, and refuse to carry on over one of Chrome's error pages."""
    timed_out = False
    try:
        driver.get(url)
    except TimeoutException:
        print(f'Page load timed out: {url}')
        timed_out = True
        try:
            driver.execute_script('window.stop();')
        except WebDriverException:
            pass

    error_code = get_chrome_error_code(driver)
    if error_code is not None:
        raise BrowserSessionLost(f'Chrome error page ({error_code})')

    return not timed_out


def open_edit_page(driver, entity_path, lngid):
    return open_page(
        driver,
        f'https://www.themoviedb.org/{entity_path}/{lngid}/edit?active_nav_item=external_ids'
    )


def dismiss_cookie_banner(driver, timeout=COOKIE_BANNER_TIMEOUT):
    """Decline TMDB's cookie banner, which otherwise covers the Save button.

    Returns False when no banner shows up, which is the normal case on a browser
    that already declined: the caller has nothing to do about it.
    """
    try:
        button = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.ID, COOKIE_DECLINE_ID))
        )
    except TimeoutException:
        return False

    try:
        button.click()
    except (ElementClickInterceptedException, ElementNotInteractableException):
        driver.execute_script('arguments[0].click();', button)

    try:
        WebDriverWait(driver, timeout).until(
            EC.invisibility_of_element_located((By.ID, COOKIE_BANNER_ID))
        )
    except TimeoutException:
        print('Cookie banner still visible after clicking Decline all.')
        return False

    print('Cookie banner declined.')
    return True


def click_save_button(driver):
    """Click Save, clearing the cookie banner out of the way if it intercepts it."""
    try:
        driver.find_element(By.XPATH, SAVE_BUTTON_XPATH).click()
        return
    except ElementClickInterceptedException:
        print('Save click intercepted: dismissing the cookie banner.')

    dismiss_cookie_banner(driver)
    save_button = driver.find_element(By.XPATH, SAVE_BUTTON_XPATH)
    try:
        save_button.click()
    except ElementClickInterceptedException:
        # The button is there and enabled, something is just sitting on top of
        # it: a scripted click reaches it whatever that something is.
        driver.execute_script('arguments[0].click();', save_button)


def find_login_fields(driver, timeout=10):
    """(form, username, password) of the visible TMDB login form, None when absent.

    Since 2026-11-06 /login carries every auth form twice (the page and a hidden
    copy in the header) and a signup form whose fields have the same names, so
    the first name="username" of the page is no longer necessarily the right one.
    """
    def visible_login_fields(d):
        for username in d.find_elements(By.NAME, 'username'):
            try:
                if not username.is_displayed():
                    continue
                form = username.find_element(By.XPATH, './ancestor::form[1]')
                if 'signup' in (form.get_attribute('action') or ''):
                    continue
                return form, username, form.find_element(By.NAME, 'password')
            except (NoSuchElementException, StaleElementReferenceException):
                continue
        return False

    try:
        return WebDriverWait(driver, timeout).until(visible_login_fields)
    except TimeoutException:
        return None


def submit_login_form(driver, form, password_field):
    """Click the form's own submit button, as a person would.

    Matched on its type, not its text: the label follows the account language
    ('Connexion', 'Login'). Enter in the password field, the only submit until
    2026-11-06, no longer logs in on the new page.
    """
    for button in form.find_elements(By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"]'):
        try:
            if not button.is_displayed():
                continue
            try:
                button.click()
            except (ElementClickInterceptedException, ElementNotInteractableException):
                dismiss_cookie_banner(driver, timeout=2)
                driver.execute_script('arguments[0].click();', button)
            return
        except StaleElementReferenceException:
            continue
    print('TMDB login form has no visible submit button: pressing Enter instead.')
    password_field.send_keys('\n')

def login_tmdb_with_credentials(driver):
    open_page(driver, 'https://www.themoviedb.org/login')
    dismiss_cookie_banner(driver)
    time.sleep(10)

    fields = find_login_fields(driver)
    if fields is None:
        # Raising here would abort a run that a restart was trying to save.
        print('TMDB login form not found: check the Chrome window.')
        return False
    form, username_field, password_field = fields

    username_field.clear()
    username_field.send_keys(tmdb_login)
    password_field.clear()
    password_field.send_keys(tmdb_password)
    submit_login_form(driver, form, password_field)

    return wait_until_logged_in(driver)

def is_tmdb_session_active(driver):
    open_page(driver, SESSION_CHECK_URL)
    return '/login' not in driver.current_url and find_login_fields(driver, timeout=3) is None


def login_tmdb(driver):
    """Reuse the TMDB session the profile keeps, and log in only when it is gone.

    First the .env credentials, as in the notebooks; when that does not go
    through (a challenge, a changed login page), the window waits
    LOGIN_MANUAL_TIMEOUT for a login by hand, which the profile then keeps.
    """
    if is_tmdb_session_active(driver):
        dismiss_cookie_banner(driver, timeout=3)
        print('TMDB session still open in the Chrome profile.')
        return True

    if login_tmdb_with_credentials(driver):
        return True

    if '/login' not in driver.current_url:
        open_page(driver, 'https://www.themoviedb.org/login')
    print(f'Log in to TMDB by hand in the Chrome window ({LOGIN_MANUAL_TIMEOUT} s): '
          'the profile keeps the session for the next runs.')
    return wait_until_logged_in(driver, timeout=LOGIN_MANUAL_TIMEOUT)


def wait_until_logged_in(driver, timeout=LOGIN_CONFIRM_TIMEOUT):
    """Wait for TMDB to leave the login page.

    A successful login redirects away from /login, a CAPTCHA or a refused login
    stays on it. The URL is the signal here rather than is_logged_out(), because
    the anonymous home page carries a login form of its own in the header.
    """
    deadline = time.time() + timeout
    warn_at = time.time() + 15
    warned = False

    while time.time() < deadline:
        if '/login' not in driver.current_url:
            print('TMDB login confirmed.')
            return True

        if not warned and time.time() >= warn_at:
            print('Still on the TMDB login page: solve the CAPTCHA in the Chrome window if one is shown.')
            warned = True

        time.sleep(5)

    print(f'TMDB login still not confirmed after {timeout} s.')
    return False


def is_browser_gone(exc):
    """True when the exception means Chrome or chromedriver stopped answering.

    A live browser raises selenium errors (a missing element, a slow page); a
    crashed one answers with an invalid session, or stops answering at all, and
    that last case surfaces as a raw urllib3 read timeout, which is not a
    WebDriverException.
    """
    if isinstance(exc, (InvalidSessionIdException, NoSuchWindowException)):
        return True

    if isinstance(exc, (urllib3.exceptions.HTTPError, ConnectionError, TimeoutError)):
        return True

    if isinstance(exc, WebDriverException):
        message = (exc.msg or str(exc)).lower()
        return any(marker in message for marker in BROWSER_GONE_MESSAGES)

    return False

def shutdown_browser(driver, timeout=BROWSER_QUIT_TIMEOUT):
    """Close Chrome without letting a hung driver block the run.

    An attached chromedriver does not own the browser, so quit() alone would leave
    it running: Chrome is asked to close through DevTools (Browser.close, sent once
    at shutdown, never between navigations), in a daemon thread since a hung
    chromedriver may never answer. A Chrome still listening afterwards is killed
    when this process launched it.
    """
    global CHROME_PROCESS

    def close_quietly():
        try:
            driver.execute_cdp_cmd('Browser.close', {})
        except Exception:
            pass
        try:
            driver.quit()
        except Exception:
            pass

    thread = threading.Thread(target=close_quietly, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        print('chromedriver did not answer in time: killing it.')
        process = getattr(getattr(driver, 'service', None), 'process', None)
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except OSError as exc:
                print(f'chromedriver could not be killed ({exc}).')

    deadline = time.time() + timeout
    while is_chrome_listening() and time.time() < deadline:
        time.sleep(0.5)

    if is_chrome_listening():
        if CHROME_PROCESS is not None and CHROME_PROCESS.poll() is None:
            print('Chrome did not close in time: killing it.')
            try:
                CHROME_PROCESS.kill()
            except OSError as exc:
                print(f'Chrome could not be killed ({exc}).')
        else:
            print('Chrome did not close and was not started by this run: close it by hand.')

    CHROME_PROCESS = None


def restart_browser(driver):
    """Replace the current browser with a fresh, logged-in one.

    Returns the new driver: the old one points at a session that no longer
    exists, so every caller must rebind.
    """
    shutdown_browser(driver)
    time.sleep(3)
    new_driver = init_driver()
    try:
        logged_in = login_tmdb(new_driver)
    except BrowserSessionLost as exc:
        # The caller counts the attempts and stops the run; raising from here
        # would abort with the login error instead of that clearer message.
        logged_in = False
        print(f'Login page could not be reached after the restart ({exc}).')

    if not logged_in:
        print('TMDB login not confirmed after the restart: check the Chrome window.')

    return new_driver


# ---------------------------------------------------------------------------
# Trace of every wikidata_id write, one JSON object per line (JSON Lines).
#
# The unit is the write ATTEMPT, not the successful write. A record TMDB
# refuses (locked field, 404, no English translation, save not confirmed) is
# the interesting half of a run, and the previous ';'-separated log, written
# only on success from process_dataset, made that half invisible.
#
# JSON Lines rather than one JSON array because the file is appended to by a
# process that is expected to be interrupted: an array has to be closed to
# parse, so a crashed run would leave an unreadable file exactly when one most
# wants to read it. Every line carries its whole context (run_id, dataset,
# mode, entity) instead of inheriting it from a header, so a handful of grepped
# lines stay self-sufficient. The redundancy costs disk and saves the reader.
#
# See SELENIUM-TMDB-015 in the Nestor backlog.
# ---------------------------------------------------------------------------
LOG_DIR = Path('./logs')
LOG_BASENAME = 'selenium-tmdb-wikidata_id'
LOG_SCHEMA_VERSION = 1

# One run identity per execution of this cell, shared by the six datasets.
RUN_ID = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:6]}"


def get_log_file_path():
    """One file per day. The date is read at write time, so a run that crosses
    midnight splits in two instead of growing one endless file."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / f"{LOG_BASENAME}-{time.strftime('%Y%m%d')}.log"


def log_value(value):
    """Coerce a pandas cell into something json.dumps accepts.

    Row values come from pandas: an id is a numpy.int64, which json refuses,
    and an empty cell is NaN, which json would write as the invalid literal NaN.
    """
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, str):
        return value
    text = str(value).strip()
    return text or None


def log_int(value):
    try:
        return int(log_value(value))
    except (TypeError, ValueError):
        return None


def append_log_event(event, **fields):
    """Append one JSON line to the day's log.

    Never raises: the trace is a witness, not a gate, and a log that cannot be
    written must not abort a run that is writing to a third-party site.
    """
    record = {
        'schema': LOG_SCHEMA_VERSION,
        'ts': datetime.now().astimezone().isoformat(timespec='milliseconds'),
        'run_id': RUN_ID,
        'event': event,
    }
    record.update(fields)

    try:
        line = json.dumps(record, ensure_ascii=False, default=str)
        with get_log_file_path().open('a', encoding='utf-8') as log_file:
            log_file.write(line + '\n')
    except (OSError, TypeError, ValueError) as exc:
        print(f'Log write failed ({type(exc).__name__}: {exc}).')


def read_field_value(field):
    """The value on the page before write_wikidata_id clears it. On a replace
    run it is the only record of what the robot destroyed."""
    try:
        return field.get_attribute('value')
    except StaleElementReferenceException:
        return None


def is_page_not_found(driver):
    elements = driver.find_elements(By.XPATH, "//h2[text()=\"Oops! We can't find the page you're looking for\"]")
    return len(elements) > 0


def is_logged_out(driver):
    return len(driver.find_elements(By.NAME, 'password')) > 0


def describe_field_state(field):
    try:
        return (
            f"displayed={field.is_displayed()} enabled={field.is_enabled()} "
            f"readonly={field.get_attribute('readonly')}"
        )
    except StaleElementReferenceException:
        return 'stale element'


def is_field_writable(field):
    try:
        return field.is_displayed() and field.is_enabled() and field.get_attribute('readonly') is None
    except StaleElementReferenceException:
        return False


CREATE_TRANSLATION_XPATH = "//button[contains(normalize-space(.), 'Create Translation')]"


def create_english_translation(driver, entity_path, lngid):
    """Create the English translation when TMDB redirects the edit page to it.

    A record without an English translation does not get an edit form: the edit
    URL lands on /translate/<entity>/<id>-<slug>, which carries no wikidata_id
    field and a 'Create Translation' button instead. Clicking it creates the
    translation and returns to the edit page.

    The button is matched on its text alone. Keying on the icon classes is what
    hid this for months: the span is 'glyphicons plus svg' on the translate page
    and 'glyphicons_v2 plus svg' elsewhere, so the class-based XPath matched
    nothing, the script concluded the translation already existed, and every such
    record was reported as 'wikidata_id field not found'. Measured on the movie
    export of 2026-09-07: 25 of the first 65 records.

    Returns False when the page cannot be brought back to an editable state.
    """
    try:
        button = driver.find_element(By.XPATH, CREATE_TRANSLATION_XPATH)
    except NoSuchElementException:
        print("Button 'Create translation' not found, translation already exists.")
        return True

    try:
        button.click()
    except (ElementClickInterceptedException, ElementNotInteractableException):
        driver.execute_script('arguments[0].click();', button)

    print("Button 'Create translation' clicked successfully.")
    time.sleep(2)
    return open_edit_page(driver, entity_path, lngid)

# ---------------------------------------------------------------------------
# Never give up: a run waits and starts again after an error instead of exiting.
#
# The cursor is stored after every record, so starting the work again resumes
# where it stopped. The waits grow, then stay at the last value; a TMDb 429 that
# outlived its own waits (TmdbThrottled) waits RETRY_WAIT_THROTTLED, a wait, never a
# workaround. A run that had kept going RETRY_RESET_AFTER seconds before failing
# starts the ladder again from the first wait.
# Only Ctrl+C and the host key check end the program: a wrong SFTP host key is a
# security failure that no wait repairs (AGENTS.md, never retried with the password).
# ---------------------------------------------------------------------------
RETRY_WAITS = (60, 300, 900, 1800)    # seconds before each new attempt, the last one repeats
RETRY_WAIT_THROTTLED = 1800           # seconds after a TMDb 429 that would not lift
RETRY_RESET_AFTER = 1800              # seconds of work after which the ladder starts over


def run_until_done(work, label, throttled_types=()):
    """Call work() until it returns, waiting after each error. Returns what work() returns.

    work is called again from scratch after an error: it must rebuild what it needs
    (CSV download, browser, login) and resume from the stored cursor.
    """
    failures = 0
    while True:
        started = time.monotonic()
        try:
            return work()
        except KeyboardInterrupt:
            raise
        except (HostKeyVerificationError, paramiko.BadHostKeyException):
            raise
        except Exception as exc:
            if time.monotonic() - started >= RETRY_RESET_AFTER:
                failures = 0
            throttled = bool(throttled_types) and isinstance(exc, throttled_types)
            wait = RETRY_WAIT_THROTTLED if throttled else RETRY_WAITS[min(failures, len(RETRY_WAITS) - 1)]
            failures += 1
            import traceback
            traceback.print_exc()
            resume_at = datetime.fromtimestamp(time.time() + wait).strftime('%H:%M:%S')
            print(f'{label}: {type(exc).__name__}: {exc}'.strip())
            print(f'{label}: error {failures}, waiting {wait} s, new attempt at {resume_at} '
                  '(Ctrl+C to stop).')
            append_log_event('run_error', label=label, error_type=type(exc).__name__,
                             error=str(exc)[:500], failure=failures, wait_s=wait, throttled=throttled)
            time.sleep(wait)


def replace_browser(driver):
    """A fresh, logged-in browser for a new attempt, whatever state the old one is in."""
    if driver is None:
        driver = init_driver()
        login_tmdb(driver)
        return driver
    return restart_browser(driver)


def close_browser_when_done(driver):
    """End of a script: leave Chrome open on its profile, as Jupyter would, and stop chromedriver only.

    The next run attaches to that window instead of starting another one.
    """
    if driver is None:
        return

    service = getattr(driver, 'service', None)
    try:
        if service is not None:
            service.stop()
    except Exception:
        pass
    print(f'Chrome stays open on {CHROME_PROFILE_DIR}: the next run attaches to it.')
