#!/usr/bin/env python
"""Primary facts into TMDb (persons_primary_facts).

Script version of selenium-tmdb-deathday.ipynb: cells 1 to 4 are copied
verbatim, cells 5 to 11 are reached through the options below. Every real run
MODIFIES LIVE RECORDS on themoviedb.org: run it deliberately, in a terminal,
while watching the browser (never from CI or cron).

The notebook's introduction (markdown cell 0):

# Primary facts into TMDb (persons_primary_facts)

Fills four fields of the TMDb person page `primary_facts` from Wikidata: **Day of Death** (P570), **Birthday** (P569), **Gender** (P21) and **Place of Birth** (P19), from the daily export `preprocess/primary-facts-person-fix.sql`. Fill only, never replace: an empty cell in the CSV means the field is left alone, a field already filled or moderator-locked on the live page is skipped, and each written field is read back after Save. Interactive only, never cron or CI.

1. Run cells 1 to 5 (imports, `.env`, helpers, primary facts code, download and login).
2. Cell 6 inspects one person, read-only: check that the four fields are found (ids `deathday`, `birthday`, `gender`, `place_of_birth`).
3. Cell 7 runs with `DRY_RUN = True` first: read what it would write, place strings above all.
4. Set `DRY_RUN = False` and a small `MAX_ROWS`, watch the browser, then raise it. `FILL_FIELDS` leaves a field out of a run.

TMDb throttles (429) after about 1,500 edits in a row: the run pauses, then stops with the cursor stored. Run cell 7 again later.

Log: `logs/selenium-tmdb-deathday-YYYYMMDD.log`, one JSON line per field attempt.

Script equivalents of the notebook cells:

    python selenium-tmdb-deathday.py --dry-run --max-rows 20   # cells 5, 7, 8 with DRY_RUN = True
    python selenium-tmdb-deathday.py                           # cells 5, 7, 8 as they stand: DRY_RUN = False,
                                                               # MAX_ROWS = 0, FILL_FIELDS = deathday birthday gender
    python selenium-tmdb-deathday.py --fields deathday birthday gender place_of_birth
    python selenium-tmdb-deathday.py --diagnostic 1265047      # cells 5 and 6, read-only
    python selenium-tmdb-deathday.py --reset-cursor            # cell 9
    python selenium-tmdb-deathday.py --debug-login             # cells 10 and 11 (login investigation)

The resume cursor is the notebook's (%store), see set_store_value below.
"""

# =============================================================================
# Notebook cell 1: imports
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

import argparse

# Jupyter runs the notebook from its own folder; a script can be started from
# anywhere. The relative paths of the code below (.env, data/, logs/) keep
# meaning the repository folder only if the script moves there first.
os.chdir(Path(__file__).resolve().parent)

# =============================================================================
# Notebook cell 2: configuration from .env
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
# Notebook cell 3: helpers (verbatim copy of cell 4 of the wikidata_id notebook)
# =============================================================================
# Shared helpers, copied verbatim from selenium-tmdb-wikidata_id.ipynb (cell 4) on 2026-11-01.
# Chrome session, login, cookie banner, crash recovery, cursor store, JSON Lines log.
# A fix made there belongs here too (see AGENTS.md).

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


def set_store_value(store_key, value):
    ip = get_ipython()
    if ip is None:
        return

    ip.user_ns[store_key] = value
    ip.run_line_magic('store', store_key)


def get_store_value(store_key, default=0):
    """Read back the cursor persisted by set_store_value.

    This is the resume half of the %store pair: without it the loop always
    restarts at the top of the CSV. Reading ip.db directly rather than
    running '%store -r' keeps an unknown key from raising on a first run.
    """
    ip = get_ipython()
    if ip is None:
        return default

    try:
        return ip.db['autorestore/' + store_key]
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


def build_chrome_options():
    """Chrome flags that slow the memory growth behind the out-of-memory crashes.

    The back/forward cache keeps each previous page alive inside the renderer the
    whole run shares, which is memory the loop never gets back: 12 measured
    navigations cost 16 MB per page with it on, 9 MB with it off.
    """
    options = webdriver.ChromeOptions()
    options.add_argument('--disable-features=BackForwardCache')
    return options


def init_driver():
    driver = webdriver.Chrome(
        service=ChromeService(ChromeDriverManager().install()),
        options=build_chrome_options()
    )
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


def login_tmdb(driver):
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

    driver.quit() talks to a chromedriver that may never answer, so it runs in a
    daemon thread and the process is killed when it does not return in time.
    """
    def quit_quietly():
        try:
            driver.quit()
        except Exception:
            pass

    thread = threading.Thread(target=quit_quietly, daemon=True)
    thread.start()
    thread.join(timeout)
    if not thread.is_alive():
        return

    print('Chrome did not close in time: killing chromedriver. A leftover Chrome window may need closing by hand.')
    process = getattr(getattr(driver, 'service', None), 'process', None)
    if process is not None and process.poll() is None:
        try:
            process.kill()
        except OSError as exc:
            print(f'chromedriver could not be killed ({exc}).')


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

TMDB_EDIT_URL = 'https://www.themoviedb.org/{entity}/{tmdb_id}/edit?active_nav_item=external_ids'


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


def log_wikidata_write(context, action, tmdb_id, outcome, reason=None,
                       wikidata_id=None, previous_wikidata_id=None, duration_ms=None):
    """One line per attempted write on TMDB, successful or not.

    action is 'set' or 'clear': the clear path erases a QID from a conflicting
    record, which is a write to TMDB and deserves a line of its own.
    outcome is 'success', 'skipped' (TMDB refused the record) or 'failed' (the
    write was attempted and did not stick), and reason names which of the two.
    """
    context = context or {}
    entity = context.get('entity')
    record_id = log_int(tmdb_id)
    target = log_value(wikidata_id)
    previous = log_value(previous_wikidata_id)

    append_log_event(
        'wikidata_id_write',
        action=action,
        outcome=outcome,
        reason=reason,
        dataset=context.get('dataset'),
        mode=context.get('mode'),
        entity=entity,
        tmdb_id=record_id,
        wikidata_id=target,
        previous_wikidata_id=previous,
        changed=(outcome == 'success' and previous != target),
        url=TMDB_EDIT_URL.format(entity=entity, tmdb_id=record_id),
        csv_file=context.get('csv_file'),
        # Coerced here and not only at the call site: a numpy.int64 slipping
        # through would be stringified by the json fallback, silently turning
        # a row number into "42".
        csv_row=log_int(context.get('csv_row')),
        attempt=log_int(context.get('attempt')) or 1,
        duration_ms=duration_ms,
    )


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


def is_wikidata_id_locked(driver):
    # Every field carries a #wikidata_id_status padlock control: the discriminating
    # class is 'locked', never 'locked_status' alone.
    css_selectors = (
        'span#wikidata_id_status.glyphicons_v2.locked.locked_status',
        'span#wikidata_id_status.locked',
    )
    for css_selector in css_selectors:
        if len(driver.find_elements(By.CSS_SELECTOR, css_selector)) > 0:
            return True
    return False


def find_visible_element(driver, by, value):
    for element in driver.find_elements(by, value):
        try:
            if element.is_displayed():
                return element
        except StaleElementReferenceException:
            continue
    return None


def activate_external_ids_panel(driver):
    """The edit page keeps every section in the DOM and only shows the active one.

    When the active_nav_item URL parameter does not take effect, click the
    'External IDs' nav link so the wikidata_id input becomes interactable.
    """
    link = find_visible_element(driver, By.CSS_SELECTOR, 'a[href*="active_nav_item=external_ids"]')
    if link is None:
        return False

    driver.execute_script('arguments[0].click();', link)
    return True


def get_wikidata_id_field(driver, lngid, timeout_message):
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, 'wikidata_id'))
        )
    except TimeoutException:
        print(timeout_message.format(lngid=lngid))
        return None

    # The panel is rendered asynchronously and several sections may each hold a
    # wikidata_id input: keep the visible one.
    try:
        field = WebDriverWait(driver, 5).until(
            lambda d: find_visible_element(d, By.NAME, 'wikidata_id')
        )
    except TimeoutException:
        field = None

    if field is None and activate_external_ids_panel(driver):
        print("Panel 'External IDs' activated manually.")
        try:
            field = WebDriverWait(driver, 10).until(
                lambda d: find_visible_element(d, By.NAME, 'wikidata_id')
            )
        except TimeoutException:
            field = None

    if field is None:
        # Fall back to the first match so the caller can report its actual state.
        field = driver.find_element(By.NAME, 'wikidata_id')

    return field


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


def write_wikidata_id(field, strwikidataid=None):
    """Clear the field, then type strwikidataid when provided.

    Returns False (instead of raising) when TMDB refuses the edit, so the batch
    loop can skip the record and carry on.
    """
    try:
        field.clear()
        if strwikidataid is not None:
            field.send_keys(strwikidataid)
        return True
    except (
        InvalidElementStateException,
        ElementNotInteractableException,
        StaleElementReferenceException,
    ) as exc:
        print(f'wikidata_id field could not be edited ({type(exc).__name__}).')
        return False


def confirm_wikidata_id(driver, expected_value):
    """Re-read the field after Save so only real writes are reported and logged."""
    def has_expected_value(d):
        field = find_visible_element(d, By.NAME, 'wikidata_id')
        if field is None:
            return False
        try:
            return field.get_attribute('value') == expected_value
        except StaleElementReferenceException:
            return False

    try:
        return WebDriverWait(driver, 10).until(has_expected_value)
    except TimeoutException:
        return False


def debug_wikidata_page(driver, entity_path, lngid):
    """Dump the state of one edit page. Read-only: nothing is written to TMDB."""
    open_edit_page(driver, entity_path, lngid)
    time.sleep(3)

    print(f'url          : {driver.current_url}')
    print(f'title        : {driver.title}')
    print(f'logged out   : {is_logged_out(driver)}')
    print(f'page 404     : {is_page_not_found(driver)}')
    print(f'locked       : {is_wikidata_id_locked(driver)}')
    print(f'save buttons : {len(driver.find_elements(By.XPATH, SAVE_BUTTON_XPATH))}')

    fields = driver.find_elements(By.NAME, 'wikidata_id')
    print(f'wikidata_id inputs: {len(fields)}')
    for position, field in enumerate(fields):
        print(f'  [{position}] {describe_field_state(field)} value={field.get_attribute("value")!r}')
        print(f'       {field.get_attribute("outerHTML")[:400]}')

    for status in driver.find_elements(By.CSS_SELECTOR, '#wikidata_id_status'):
        print(f'  status: {status.get_attribute("outerHTML")[:300]}')


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


def set_wikidata_id(driver, entity_path, lngid, strwikidataid, timeout_message, context=None):
    started = time.monotonic()
    previous_value = None

    def trace(outcome, reason=None):
        log_wikidata_write(
            context, 'set', lngid, outcome, reason,
            wikidata_id=strwikidataid,
            previous_wikidata_id=previous_value,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    if not open_edit_page(driver, entity_path, lngid):
        trace('failed', 'page_load_timeout')
        return False

    intpagefound = True
    try:
        if is_page_not_found(driver):
            print("Element 'Page 404' exists on the page.")
            intpagefound = False
        else:
            print("Element 'Page 404' does not exist on the page.")
    except NoSuchElementException:
        print("Element 'Page 404' does not exist on the page.")

    if not intpagefound:
        trace('skipped', 'page_not_found')
        return False

    if not create_english_translation(driver, entity_path, lngid):
        trace('failed', 'translation_failed')
        return False

    wikidata_id_field = get_wikidata_id_field(driver, lngid, timeout_message)
    if wikidata_id_field is None:
        if is_logged_out(driver):
            trace('failed', 'session_lost')
            raise BrowserSessionLost('TMDB redirected to the login page')
        trace('skipped', 'field_not_found')
        return False

    previous_value = read_field_value(wikidata_id_field)

    if is_wikidata_id_locked(driver):
        print("Element 'Locked' exists on the page.")
        trace('skipped', 'locked')
        return False

    if not is_field_writable(wikidata_id_field):
        print(
            f'wikidata_id field is not editable for {entity_path} {lngid} '
            f'({describe_field_state(wikidata_id_field)}). Skipping.'
        )
        trace('skipped', 'field_not_editable')
        return False

    if not write_wikidata_id(wikidata_id_field, strwikidataid):
        print(f'Skipping {entity_path} {lngid}.')
        trace('skipped', 'field_write_refused')
        return False

    click_save_button(driver)

    if not confirm_wikidata_id(driver, strwikidataid):
        print(f'Save not confirmed for {entity_path} {lngid}: {strwikidataid} was not applied.')
        trace('failed', 'save_not_confirmed')
        return False

    print(f'{entity_path} {lngid} updated with {strwikidataid}.')
    trace('success')
    return True


def clear_wikidata_id(driver, entity_path, lngid, context=None):
    started = time.monotonic()
    previous_value = None

    def trace(outcome, reason=None):
        log_wikidata_write(
            context, 'clear', lngid, outcome, reason,
            wikidata_id=None,
            previous_wikidata_id=previous_value,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    if not open_edit_page(driver, entity_path, lngid):
        trace('failed', 'page_load_timeout')
        return False

    if is_page_not_found(driver):
        print("Element 'Page 404' exists on the page. Skipping clear.")
        trace('skipped', 'page_not_found')
        return False

    wikidata_id_field = get_wikidata_id_field(
        driver, lngid, f'wikidata_id field not found for {entity_path} {{lngid}}. Skipping clear.'
    )
    if wikidata_id_field is None:
        if is_logged_out(driver):
            trace('failed', 'session_lost')
            raise BrowserSessionLost('TMDB redirected to the login page')
        trace('skipped', 'field_not_found')
        return False

    previous_value = read_field_value(wikidata_id_field)

    if is_wikidata_id_locked(driver):
        print("Element 'Locked' exists on the page. Skipping clear.")
        trace('skipped', 'locked')
        return False

    if not is_field_writable(wikidata_id_field):
        print(
            f'wikidata_id field is not editable for {entity_path} {lngid} '
            f'({describe_field_state(wikidata_id_field)}). Skipping clear.'
        )
        trace('skipped', 'field_not_editable')
        return False

    if not write_wikidata_id(wikidata_id_field):
        print(f'Skipping clear for {entity_path} {lngid}.')
        trace('skipped', 'field_write_refused')
        return False

    click_save_button(driver)

    if not confirm_wikidata_id(driver, ''):
        print(f'Clear not confirmed for {entity_path} {lngid}.')
        trace('failed', 'save_not_confirmed')
        return False

    trace('success')
    return True


def process_row(driver, dataset, lngid, strwikidataid, strtmdbidtoerase, context=None):
    """Apply one CSV row to TMDB, assuming a live browser.

    Raises instead of returning when the browser or the session is gone, so the
    caller restarts Chrome and tries the row again rather than storing a cursor
    past a record that was never written.
    """
    if pd.isna(strtmdbidtoerase):
        print('strtmdbidtoerase is NaN')
    else:
        print('strtmdbidtoerase is not NaN')
        lngtmdbidtoerase = int(strtmdbidtoerase)
        clear_wikidata_id(driver, dataset['entity_path'], lngtmdbidtoerase, context)

    return set_wikidata_id(
        driver,
        dataset['entity_path'],
        lngid,
        strwikidataid,
        dataset['timeout_message'],
        context
    )


def process_row_with_recovery(driver, dataset, lngid, strwikidataid, strtmdbidtoerase, context=None):
    """Run process_row, restarting Chrome when it dies under the row.

    Returns (driver, was_updated). After a restart the driver is a new one, so
    the caller must keep what comes back: the old session no longer exists.
    """
    for attempt in range(1, BROWSER_RESTART_ATTEMPTS + 1):
        # The attempt number goes into the trace, so a record written on the
        # second try is not read later as two records.
        attempt_context = dict(context or {}, attempt=attempt)
        try:
            return driver, process_row(
                driver, dataset, lngid, strwikidataid, strtmdbidtoerase, attempt_context
            )
        except BrowserSessionLost as exc:
            reason = str(exc)
        except Exception as exc:
            if not is_browser_gone(exc):
                raise
            reason = f'{type(exc).__name__}: {exc}'.strip()

        entity_path = dataset['entity_path']
        print(
            f'Browser lost on {entity_path} {lngid} ({reason}). '
            f'Attempt {attempt}/{BROWSER_RESTART_ATTEMPTS}.'
        )
        if attempt == BROWSER_RESTART_ATTEMPTS:
            break

        driver = restart_browser(driver)

    raise RuntimeError(
        f"Chrome could not be kept alive for {dataset['entity_path']} {lngid} after "
        f"{BROWSER_RESTART_ATTEMPTS} attempts. The {dataset['store_key']} cursor is stored: "
        'fix the browser, then run the cell again to resume where it stopped.'
    )


def process_dataset(driver, dataset):
    """Walk one CSV and apply every row, returning the driver still in use.

    Chrome is restarted in place when it crashes, so the caller must rebind:
    driver = process_dataset(driver, dataset).
    """
    latest_csv = get_latest_csv(dataset['local_folder'], dataset['local_file_basename'])
    data = pd.read_csv(str(latest_csv), sep=';', quotechar='"')
    print(data.shape)

    store_key = dataset['store_key']
    start_value = get_store_value(store_key, 0)
    print(f'{store_key} = {start_value}')
    processed_count = 0
    updated_count = 0
    skipped_count = 0
    consecutive_skips = 0
    skip_restarts = 0
    dataset_started = time.monotonic()

    # Stamped on every log line of this dataset, so a line grepped out of the
    # file says on its own which export and which row it came from.
    base_context = {
        'dataset': dataset['name'],
        'mode': dataset.get('mode'),
        'entity': dataset['entity_path'],
        'csv_file': latest_csv.name,
    }

    # The two framing events carry the denominators: without the row count and
    # the counters, a success rate cannot be computed from the file alone.
    append_log_event(
        'dataset_start',
        dataset=dataset['name'],
        mode=dataset.get('mode'),
        entity=dataset['entity_path'],
        csv_file=latest_csv.name,
        csv_rows=int(data.shape[0]),
        cursor_key=store_key,
        cursor_start=log_int(start_value),
    )

    def log_dataset_end(status):
        append_log_event(
            'dataset_end',
            dataset=dataset['name'],
            mode=dataset.get('mode'),
            entity=dataset['entity_path'],
            csv_file=latest_csv.name,
            status=status,
            processed=processed_count,
            updated=updated_count,
            skipped=skipped_count,
            cursor_key=store_key,
            cursor_end=log_int(start_value),
            duration_s=round(time.monotonic() - dataset_started, 1),
        )

    if dataset.get('name') == 'persons' and not dataset.get('intgoingdown', True):
        rows = data.iloc[::-1].iterrows()
        comparator = lambda current_id, last_id: current_id < last_id
    else:
        rows = data.iterrows()
        comparator = lambda current_id, last_id: current_id > last_id

    try:
        for index, row in rows:
            print(f'Index: {index} ; processed: {processed_count}')

            if row[dataset['id_column']]:
                lngid = row[dataset['id_column']]
                if row['ID_WIKIDATA']:
                    strwikidataid = row['ID_WIKIDATA']
                    strtmdbidtoerase = row[dataset['erase_column']]
                    if comparator(lngid, start_value):
                        driver, was_updated = process_row_with_recovery(
                            driver, dataset, lngid, strwikidataid, strtmdbidtoerase,
                            dict(base_context, csv_row=log_int(index))
                        )
                        if was_updated:
                            updated_count += 1
                            consecutive_skips = 0
                            skip_restarts = 0
                        else:
                            skipped_count += 1
                            consecutive_skips += 1

                        processed_count += 1
                        start_value = lngid
                        set_store_value(store_key, start_value)

                        if consecutive_skips >= MAX_CONSECUTIVE_SKIPS:
                            if skip_restarts:
                                raise RuntimeError(
                                    f'{consecutive_skips} records in a row wrote nothing, and a fresh '
                                    f'browser did not change that. The {store_key} cursor is stored: '
                                    'check TMDB in the window before resuming.'
                                )
                            print(f'{consecutive_skips} records in a row wrote nothing: restarting Chrome.')
                            skip_restarts += 1
                            consecutive_skips = 0
                            driver = restart_browser(driver)
                        elif BROWSER_RECYCLE_EVERY and processed_count % BROWSER_RECYCLE_EVERY == 0:
                            print(f'{processed_count} records processed: recycling Chrome.')
                            driver = restart_browser(driver)

                        time.sleep(2)
                else:
                    print(dataset['missing_wikidata_message'])
            else:
                print(dataset['missing_entity_message'])
    except BaseException:
        # BaseException on purpose: a run is normally ended with the interrupt
        # button, and that ending deserves a closing line as much as a crash.
        log_dataset_end('aborted')
        raise

    log_dataset_end('completed')
    return driver

# =============================================================================
# Notebook cell 4: primary facts
# =============================================================================
# ---------------------------------------------------------------------------
# PRIMARY FACTS: the persons_primary_facts dataset (Day of Death since 2026-11-01;
# Birthday, Gender and Place of Birth added 2026-11-02).
#
# Source: preprocess/primary-facts-person-fix.sql, one row per person, one column per
# field. FILL ONLY, decided three times:
# 1. the export leaves a cell empty unless Wikidata has one clean value, the QID is
#    proven to be this person (P4985 or P345 points back at the record) and the field
#    is empty in our TMDb copy. AN EMPTY CELL MEANS "LEAVE THIS FIELD ALONE", never
#    "clear it": the robot does not even look at that field;
# 2. on the live page, a field that already holds a value, or is moderator-locked
#    (span#<field>_status with the 'locked' class token), is skipped, alone: the other
#    fields of the same person are still filled;
# 3. after Save the page is reloaded and every written field is read back; only a
#    value read back counts as success. Fields the robot did not touch are posted
#    back exactly as TMDb loaded them.
#
# Other points, all deliberate:
# - FILL_FIELDS lists the fields this run may write. Remove 'place_of_birth' (or any
#   other) to leave it out of a run without touching the export;
# - the CSV is sorted by popularity, so the cursor is a row number tied to the CSV
#   file name: a new export restarts at its top;
# - every (person, field) a previous real run wrote, or found locked or already set,
#   is read back from the logs and skipped, so a lag of the TMDb crawler never produces
#   a second edit. The death dates of the first runs (event 'deathday_write') count;
# - this tab saves through a background request and keeps the page, so the robot
#   waits for the save request itself to answer (wait_for_save), not for the page to
#   change (a full SAVE_RELOAD_TIMEOUT per record until 1.0.13);
# - TMDb throttles: after about 1,500 edits on 2026-11-02 every page answered "Too
#   Many Requests (429)" for hours, which the robot took for 16 missing fields. A
#   throttled page now pauses the run (THROTTLE_WAITS), is never counted as a skip,
#   and stops the run with the cursor stored when the waits run out. PAUSE_BETWEEN_ROWS
#   spaces the records out;
# - DRY_RUN opens each page, checks it and logs what it would write, and never clicks
#   Save. It is on by default: turn it off only after reading a dry run.
# ---------------------------------------------------------------------------
LOG_BASENAME = 'selenium-tmdb-deathday'

PRIMARY_FACTS_DATASET = {
    'name': 'persons_primary_facts',
    'remote_folder': 'primary-facts-person-fix',
    'local_folder': 'primary-facts-person-fix',
    'local_file_basename': 'primary-facts-person-fix',
    'mode': 'fill',
    'entity_path': 'person',
    'store_key': 'primaryfactscursor',
}

DRY_RUN = False
MAX_ROWS = 0          # records per run; 0 for no limit
FILL_FIELDS = ['deathday', 'birthday', 'gender', 'place_of_birth']
SAVE_RELOAD_TIMEOUT = 15
PAUSE_BETWEEN_ROWS = 2           # seconds between two persons
THROTTLE_WAITS = (60, 300, 900)  # seconds to wait on a 429 page before giving up

PRIMARY_FACTS_URL = 'https://www.themoviedb.org/person/{tmdb_id}/edit?active_nav_item=primary_facts'

# One entry per field: page element id (input or select), CSV column, kind.
# TMDb gender codes: 0 not specified, 1 female, 2 male, 3 non-binary.
PRIMARY_FIELDS = {
    'deathday':       {'column': 'DATE_OF_DEATH',  'kind': 'date',   'label': 'Day of Death'},
    'birthday':       {'column': 'DATE_OF_BIRTH',  'kind': 'date',   'label': 'Birthday'},
    'gender':         {'column': 'GENDER',         'kind': 'gender', 'label': 'Gender'},
    'place_of_birth': {'column': 'PLACE_OF_BIRTH', 'kind': 'text',   'label': 'Place of Birth'},
}
GENDER_LABELS = {'0': 'Not specified', '1': 'Female', '2': 'Male', '3': 'Non-binary'}


class TmdbThrottled(RuntimeError):
    """TMDb kept answering 429 after every wait of THROTTLE_WAITS."""


def open_primary_facts(driver, lngid):
    return open_page(driver, PRIMARY_FACTS_URL.format(tmdb_id=lngid))


def is_throttled(driver):
    try:
        return 'Too Many Requests' in (driver.title or '')
    except WebDriverException:
        return False


def open_primary_facts_patiently(driver, lngid):
    """open_primary_facts, waiting out TMDb's throttling. Raises TmdbThrottled."""
    loaded = open_primary_facts(driver, lngid)
    for wait in THROTTLE_WAITS:
        if not is_throttled(driver):
            return loaded
        print(f'TMDB throttles (429) on person {lngid}: waiting {wait} s.')
        append_log_event('throttled', entity='person', tmdb_id=log_int(lngid), wait_s=wait)
        time.sleep(wait)
        loaded = open_primary_facts(driver, lngid)
    if is_throttled(driver):
        raise TmdbThrottled(f'TMDB still answers 429 after waiting {sum(THROTTLE_WAITS)} s')
    return loaded


def parse_page_date(text):
    """A date field as a date, None when empty, a marker string when unreadable."""
    text = (text or '').strip()
    if not text:
        return None
    for fmt in ('%m/%d/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return f'unparsed:{text}'


def parse_target(key, raw):
    """The CSV cell as the value to write, None when the cell is empty (leave the field alone)."""
    if raw is None:
        return None
    text = str(raw).strip()
    # preprocess/selenium-tmdb.py writes an SQL NULL as the text "NULL" (f_csv_escape_value):
    # without this test the robot would type "NULL" as a Place of Birth.
    if not text or text.upper() in ('NULL', 'NAN', 'NONE'):
        return None
    kind = PRIMARY_FIELDS[key]['kind']
    if kind == 'date':
        return datetime.strptime(text, '%Y-%m-%d').date()
    if kind == 'gender':
        text = text.split('.')[0]  # '2.0' if pandas ever reads the column as float
        return text if text in ('1', '2', '3') else None
    return ' '.join(text.split())


def page_value(key, raw):
    """What the page shows, normalised like parse_target. None means empty."""
    kind = PRIMARY_FIELDS[key]['kind']
    if kind == 'date':
        return parse_page_date(raw)
    text = ' '.join((raw or '').split())
    if kind == 'gender':
        return None if text in ('', '0') else text
    return text or None


def display_value(key, value):
    if PRIMARY_FIELDS[key]['kind'] == 'gender':
        return f'{value} ({GENDER_LABELS.get(str(value), "?")})'
    return str(value)


def get_primary_field(driver, key, timeout=0):
    """The input or select whose id is key, None when the page has none."""
    if timeout:
        try:
            WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.ID, key)))
        except TimeoutException:
            return None
    elements = driver.find_elements(By.ID, key)
    return elements[0] if elements else None


def is_primary_field_locked(driver, key):
    return len(driver.find_elements(By.CSS_SELECTOR, f'span#{key}_status.locked')) > 0


def is_primary_field_writable(driver, field):
    """A Kendo widget hides its input or select behind its own control: judge the widget."""
    has_widget = driver.execute_script(
        "const j = window.jQuery && jQuery(arguments[0]);"
        "return !!(j && (j.data('kendoDropDownList') || j.data('kendoDatePicker') || j.data('kendoComboBox')));",
        field)
    if has_widget:
        try:
            return field.is_enabled() and field.get_attribute('readonly') is None
        except StaleElementReferenceException:
            return False
    return is_field_writable(field)


def write_primary_field(driver, field, key, value):
    """Set one field through its Kendo widget when it has one, by typing otherwise.

    Returns True only when the field then reads back the intended value.
    """
    kind = PRIMARY_FIELDS[key]['kind']
    try:
        if kind == 'date':
            done = driver.execute_script(
                """
                const el = arguments[0], y = arguments[1], m = arguments[2], d = arguments[3];
                const w = window.jQuery && jQuery(el).data('kendoDatePicker');
                if (!w) return false;
                w.value(new Date(y, m - 1, d));
                w.trigger('change');
                return true;
                """,
                field, value.year, value.month, value.day)
            if not done:
                field.clear()
                field.send_keys(value.isoformat())
        elif kind == 'gender':
            done = driver.execute_script(
                """
                const el = arguments[0], v = arguments[1];
                const j = window.jQuery && jQuery(el);
                const w = j && (j.data('kendoDropDownList') || j.data('kendoComboBox'));
                if (w) { w.value(v); w.trigger('change'); return true; }
                if (el.tagName === 'SELECT') {
                  el.value = v;
                  el.dispatchEvent(new Event('change', {bubbles: true}));
                  return true;
                }
                return false;
                """,
                field, value)
            if not done:
                print(f'{key}: neither a select nor a Kendo widget, not written.')
                return False
        else:
            field.clear()
            field.send_keys(value)
            driver.execute_script(
                "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));", field)
    except (InvalidElementStateException, ElementNotInteractableException,
            StaleElementReferenceException) as exc:
        print(f'{key} field could not be edited ({type(exc).__name__}).')
        return False

    return page_value(key, read_field_value(field)) == value


# Counts this page's own non-GET requests (XHR and fetch), so the robot knows when
# the background save has answered. Analytics and ads go to other origins and GETs
# are reads, so neither can keep the wait open. Installed again on each page.
SAVE_TRACKER_JS = """
if (!window.__deathdaySave) {
  const s = window.__deathdaySave = {started: 0, done: 0, statuses: []};
  const tracked = (method, url) => {
    if (String(method || 'GET').toUpperCase() === 'GET') return false;
    try { return new URL(url, location.href).origin === location.origin; } catch (e) { return false; }
  };
  const open = XMLHttpRequest.prototype.open, send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__deathdayTracked = tracked(method, url);
    return open.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function () {
    if (this.__deathdayTracked) {
      s.started++;
      this.addEventListener('loadend', () => { s.done++; s.statuses.push(this.status); });
    }
    return send.apply(this, arguments);
  };
  if (window.fetch) {
    const fetch0 = window.fetch;
    window.fetch = function (input, init) {
      const method = (init && init.method) || (input && input.method);
      const url = typeof input === 'string' ? input : (input && input.url) || String(input);
      if (!tracked(method, url)) return fetch0.apply(this, arguments);
      s.started++;
      return fetch0.apply(this, arguments).then(
        r => { s.done++; s.statuses.push(r.status); return r; },
        e => { s.done++; s.statuses.push(0); throw e; });
    };
  }
}
"""


def wait_for_save(driver, field, timeout=SAVE_RELOAD_TIMEOUT):
    """Wait until the save answered: its request completed, or the page was replaced.

    Returns the HTTP statuses seen ([] after a page change), None on timeout.
    Either way the caller reads the fields back from a fresh page.
    """
    def settled(d):
        if EC.staleness_of(field)(d):
            return []
        state = d.execute_script('return window.__deathdaySave || null;')
        if state and state['started'] and state['done'] >= state['started']:
            return list(state['statuses'])
        return False

    try:
        return WebDriverWait(driver, timeout, poll_frequency=0.2).until(settled)
    except TimeoutException:
        return None


def log_primary_fact_write(context, lngid, key, outcome, reason=None, value=None,
                           previous=None, duration_ms=None):
    context = context or {}
    record_id = log_int(lngid)
    if hasattr(value, 'isoformat'):
        value = value.isoformat()
    append_log_event(
        'primary_fact_write',
        action='set',
        field=key,
        outcome=outcome,
        reason=reason,
        dry_run=DRY_RUN,
        dataset=context.get('dataset'),
        mode=context.get('mode'),
        entity='person',
        tmdb_id=record_id,
        name=context.get('name'),
        wikidata_id=context.get('wikidata_id'),
        identity=context.get('identity'),
        value=log_value(value),
        previous=log_value(previous),
        url=PRIMARY_FACTS_URL.format(tmdb_id=record_id),
        csv_file=context.get('csv_file'),
        csv_row=log_int(context.get('csv_row')),
        attempt=log_int(context.get('attempt')) or 1,
        duration_ms=duration_ms,
    )


def already_handled_fields():
    """(person, field) pairs a previous real run wrote, or found locked or already set."""
    handled = set()
    for path in LOG_DIR.glob(f'{LOG_BASENAME}-*.log'):
        with path.open(encoding='utf-8') as log_file:
            for line in log_file:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record.get('dry_run'):
                    continue
                event = record.get('event')
                if event == 'deathday_write':      # first runs, Day of Death only
                    key = 'deathday'
                elif event == 'primary_fact_write':
                    key = record.get('field')
                else:
                    continue
                if record.get('outcome') == 'success' or record.get('reason') in ('locked', 'already_set'):
                    handled.add((record.get('tmdb_id'), key))
    return handled


def set_primary_facts(driver, lngid, targets, context=None):
    """Fill the empty fields of one person. targets maps field key -> value to write.

    Returns 'written' (at least one field confirmed), 'skipped' or 'dry_run'.
    Raises BrowserSessionLost when TMDB logged us out, so the caller restarts
    Chrome and retries the row; raises TmdbThrottled when TMDB keeps answering 429.
    """
    started = time.monotonic()
    previous = {}

    def trace(key, outcome, reason=None):
        log_primary_fact_write(context, lngid, key, outcome, reason, targets.get(key),
                               previous.get(key), int((time.monotonic() - started) * 1000))

    def trace_all(outcome, reason, keys=None):
        for key in (keys or targets):
            trace(key, outcome, reason)

    if not open_primary_facts_patiently(driver, lngid):
        trace_all('failed', 'page_load_timeout')
        return 'skipped'

    if is_page_not_found(driver):
        trace_all('skipped', 'page_not_found')
        return 'skipped'

    if '/translate/' in driver.current_url:
        if not create_english_translation(driver, 'person', lngid) or not open_primary_facts_patiently(driver, lngid):
            trace_all('failed', 'translation_failed')
            return 'skipped'

    # Every primary_facts page has the Day of Death field: its absence means the
    # page itself is wrong (logged out, error page), not that one field is missing.
    if get_primary_field(driver, 'deathday', timeout=10) is None:
        if is_logged_out(driver):
            trace_all('failed', 'session_lost')
            raise BrowserSessionLost('TMDB redirected to the login page')
        trace_all('skipped', 'field_not_found')
        return 'skipped'

    plan = {}
    for key, value in targets.items():
        label = PRIMARY_FIELDS[key]['label']
        field = get_primary_field(driver, key)
        if field is None:
            print(f'person {lngid}: no {label} field (#{key}) on the page. Skipping it.')
            trace(key, 'skipped', 'field_not_found')
            continue
        current = page_value(key, read_field_value(field))
        if current is not None:
            previous[key] = str(current)
            print(f'person {lngid}: {label} already {display_value(key, current)} on TMDB. Skipping it.')
            trace(key, 'skipped', 'already_set')
            continue
        if is_primary_field_locked(driver, key):
            print(f'person {lngid}: {label} is locked. Skipping it.')
            trace(key, 'skipped', 'locked')
            continue
        if not is_primary_field_writable(driver, field):
            print(f'person {lngid}: {label} not editable ({describe_field_state(field)}). Skipping it.')
            trace(key, 'skipped', 'field_not_editable')
            continue
        plan[key] = field

    if not plan:
        return 'skipped'

    name = (context or {}).get('name')
    if DRY_RUN:
        for key in plan:
            print(f"DRY RUN person {lngid} {name}: would set {PRIMARY_FIELDS[key]['label']} "
                  f"{display_value(key, targets[key])}.")
            trace(key, 'skipped', 'dry_run')
        return 'dry_run'

    for key in list(plan):
        if not write_primary_field(driver, plan[key], key, targets[key]):
            trace(key, 'skipped', 'field_write_refused')
            del plan[key]
    if not plan:
        return 'skipped'

    any_field = next(iter(plan.values()))
    driver.execute_script(SAVE_TRACKER_JS)
    click_save_button(driver)
    statuses = wait_for_save(driver, any_field)
    if statuses is None:
        print(f'person {lngid}: no answer to Save after {SAVE_RELOAD_TIMEOUT} s, reading the page back anyway.')
    elif any(status >= 400 or status == 0 for status in statuses):
        print(f'person {lngid}: Save answered {statuses}, reading the page back.')

    # Read back from a fresh page: the fields the robot filled prove nothing.
    try:
        reloaded = open_primary_facts_patiently(driver, lngid)
    except TmdbThrottled:
        trace_all('failed', 'save_not_confirmed', plan)
        raise
    if not reloaded or get_primary_field(driver, 'deathday', timeout=10) is None:
        trace_all('failed', 'save_not_confirmed', plan)
        return 'skipped'

    written = []
    for key in plan:
        label = PRIMARY_FIELDS[key]['label']
        field = get_primary_field(driver, key)
        if field is None or page_value(key, read_field_value(field)) != targets[key]:
            print(f'person {lngid}: {label} not confirmed, {display_value(key, targets[key])} was not applied.')
            trace(key, 'failed', 'save_not_confirmed')
            continue
        trace(key, 'success')
        written.append(f'{label} {display_value(key, targets[key])}')

    if not written:
        return 'skipped'
    print(f"person {lngid} updated: {'; '.join(written)}.")
    return 'written'


def set_primary_facts_with_recovery(driver, lngid, targets, context=None):
    """set_primary_facts, restarting Chrome when it dies under the row. Returns (driver, result)."""
    for attempt in range(1, BROWSER_RESTART_ATTEMPTS + 1):
        attempt_context = dict(context or {}, attempt=attempt)
        try:
            return driver, set_primary_facts(driver, lngid, targets, attempt_context)
        except BrowserSessionLost as exc:
            reason = str(exc)
        except TmdbThrottled:
            raise
        except Exception as exc:
            if not is_browser_gone(exc):
                raise
            reason = f'{type(exc).__name__}: {exc}'.strip()

        print(f'Browser lost on person {lngid} ({reason}). Attempt {attempt}/{BROWSER_RESTART_ATTEMPTS}.')
        if attempt == BROWSER_RESTART_ATTEMPTS:
            break
        driver = restart_browser(driver)

    raise RuntimeError(
        f'Chrome could not be kept alive for person {lngid} after {BROWSER_RESTART_ATTEMPTS} attempts. '
        'The cursor is stored: fix the browser, then run the cell again to resume.'
    )


def process_primary_facts(driver, dataset=PRIMARY_FACTS_DATASET, max_rows=None):
    """Walk the latest primary facts export, most popular first. Returns the driver in use."""
    max_rows = MAX_ROWS if max_rows is None else max_rows
    unknown = [key for key in FILL_FIELDS if key not in PRIMARY_FIELDS]
    if unknown:
        raise ValueError(f'FILL_FIELDS has unknown fields: {unknown}')
    latest_csv = get_latest_csv(dataset['local_folder'], dataset['local_file_basename'])
    data = pd.read_csv(str(latest_csv), sep=';', quotechar='"', dtype=str, keep_default_na=False)
    print(data.shape)

    store_key = dataset['store_key']
    cursor = get_store_value(store_key, {}) or {}
    start_row = cursor.get('row', -1) if cursor.get('csv_file') == latest_csv.name else -1
    if DRY_RUN:
        start_row = -1  # a dry run never moves the cursor, so it always starts at the top
    handled = already_handled_fields()
    print(f'DRY_RUN={DRY_RUN} MAX_ROWS={max_rows} FILL_FIELDS={FILL_FIELDS} '
          f'start_row={start_row} fields already handled={len(handled)}')

    counts = {'written': 0, 'skipped': 0, 'dry_run': 0}
    processed = consecutive_skips = skip_restarts = 0
    started = time.monotonic()
    base_context = {'dataset': dataset['name'], 'mode': dataset['mode'], 'csv_file': latest_csv.name}

    append_log_event('dataset_start', dataset=dataset['name'], mode=dataset['mode'], entity='person',
                     dry_run=DRY_RUN, csv_file=latest_csv.name, csv_rows=int(data.shape[0]),
                     cursor_key=store_key, cursor_start=start_row, max_rows=max_rows,
                     fields=list(FILL_FIELDS))

    def log_end(status):
        append_log_event('dataset_end', dataset=dataset['name'], mode=dataset['mode'], entity='person',
                         dry_run=DRY_RUN, csv_file=latest_csv.name, status=status, processed=processed,
                         updated=counts['written'], skipped=counts['skipped'], dry_runs=counts['dry_run'],
                         duration_s=round(time.monotonic() - started, 1))

    try:
        for index, row in data.iterrows():
            if index <= start_row:
                continue
            if max_rows and processed >= max_rows:
                print(f'MAX_ROWS={max_rows} reached.')
                break

            lngid = log_int(row['ID_PERSON'])
            if lngid is None:
                continue
            targets = {}
            for key in FILL_FIELDS:
                if (lngid, key) in handled:
                    continue
                try:
                    value = parse_target(key, row.get(PRIMARY_FIELDS[key]['column']))
                except ValueError:
                    print(f"person {lngid}: unreadable {PRIMARY_FIELDS[key]['column']} "
                          f"{row.get(PRIMARY_FIELDS[key]['column'])!r}. Leaving it.")
                    continue
                if value is not None:
                    targets[key] = value
            if not targets:
                continue

            context = dict(base_context, csv_row=int(index), name=log_value(row['NAME']),
                           wikidata_id=log_value(row['ID_WIKIDATA']),
                           identity=log_value(row.get('IDENTITY')))
            driver, result = set_primary_facts_with_recovery(driver, lngid, targets, context)
            counts[result] += 1
            processed += 1

            if result == 'written':
                consecutive_skips = skip_restarts = 0
            elif result == 'skipped':
                consecutive_skips += 1

            if not DRY_RUN:
                set_store_value(store_key, {'csv_file': latest_csv.name, 'row': int(index)})

            if consecutive_skips >= MAX_CONSECUTIVE_SKIPS:
                if skip_restarts:
                    raise RuntimeError(
                        f'{consecutive_skips} records in a row wrote nothing, and a fresh browser did not '
                        'change that. The cursor is stored: check TMDB in the window before resuming.'
                    )
                print(f'{consecutive_skips} records in a row wrote nothing: restarting Chrome.')
                skip_restarts += 1
                consecutive_skips = 0
                driver = restart_browser(driver)
            elif BROWSER_RECYCLE_EVERY and processed % BROWSER_RECYCLE_EVERY == 0:
                print(f'{processed} records processed: recycling Chrome.')
                driver = restart_browser(driver)

            time.sleep(PAUSE_BETWEEN_ROWS)
    except TmdbThrottled as exc:
        log_end('throttled')
        print(f'{exc}. The cursor is stored: run the cell again later to resume.')
        return driver
    except BaseException:
        log_end('aborted')
        raise

    log_end('completed')
    print(f"Done: {counts['written']} written, {counts['skipped']} skipped, {counts['dry_run']} dry run.")
    return driver


def debug_primary_facts_page(driver, lngid):
    """Dump the primary facts fields of one person. Read-only: nothing is written to TMDB."""
    open_primary_facts(driver, lngid)
    time.sleep(3)
    print(f'url        : {driver.current_url}')
    print(f'title      : {driver.title}')
    print(f'throttled  : {is_throttled(driver)}')
    print(f'logged out : {is_logged_out(driver)}')
    print(f'page 404   : {is_page_not_found(driver)}')
    for key in PRIMARY_FIELDS:
        field = get_primary_field(driver, key)
        if field is None:
            print(f'{key:<15}: NOT FOUND (#{key})')
            continue
        widget = driver.execute_script(
            "const j = window.jQuery && jQuery(arguments[0]);"
            "return j ? Object.keys(j.data()).filter(k => /kendo/i.test(k)).join(',') : '';", field)
        print(f'{key:<15}: {read_field_value(field)!r} <{field.tag_name}> widget={widget or "-"} '
              f'locked={is_primary_field_locked(driver, key)} ({describe_field_state(field)})')
    # Every other field of the tab, to find an id the table above got wrong.
    others = driver.execute_script(
        "return [...document.querySelectorAll('form input, form select, form textarea')]"
        ".filter(e => e.id && e.type !== 'hidden')"
        ".map(e => e.tagName.toLowerCase() + '#' + e.id + '=' + JSON.stringify(e.value).slice(0, 40));")
    print(f'all fields : {others}')

# =============================================================================
# Script only: %store outside Jupyter, end of run
# =============================================================================
# The helpers above persist the resume cursor with the IPython %store magic,
# through get_ipython(), which is None outside Jupyter: the cursor would be
# neither read nor written. These two functions replace them and read/write the
# very database %store uses (<IPython dir>/profile_default/db, keys
# 'autorestore/<name>'), so the notebook and the script share their cursors:
# a run stopped in one resumes in the other.


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


def close_browser_when_done(driver):
    """Jupyter leaves Chrome open after the last cell; the end of a script kills it.

    Keep the window on screen until Enter, so the browser can be checked the way
    it could after the notebook, then close it cleanly.
    """
    if driver is None:
        return

    if sys.stdin.isatty():
        try:
            input('Press Enter to close Chrome...')
        except (EOFError, KeyboardInterrupt):
            pass

    shutdown_browser(driver)

# =============================================================================
# Notebook cells 5 to 11
# =============================================================================
def debug_login(driver):
    # Cell 10
    open_page(driver, 'https://www.themoviedb.org/login')
    time.sleep(10)
    print('url  :', driver.current_url)
    print('title:', driver.title)
    print(driver.execute_script("""
    return {
      forms: [...document.forms].map(f => (f.id || '-') + ' action=' + f.getAttribute('action') + ' method=' + f.method),
      inputs: [...document.querySelectorAll('input')].filter(e => e.type !== 'hidden')
              .map(e => e.tagName.toLowerCase() + ' name=' + e.name + ' id=' + e.id + ' visible=' + !!e.offsetParent),
      buttons: [...document.querySelectorAll('button, input[type=submit]')]
              .map(b => (b.innerText || b.value || '').trim().slice(0, 40) + ' visible=' + !!b.offsetParent),
      iframes: [...document.querySelectorAll('iframe')].map(f => f.src.slice(0, 80)),
      errors: [...document.querySelectorAll('.error, .alert, [role=alert]')].map(e => e.innerText.trim().slice(0, 120)),
    };
    """))

    # Cell 11
    ok = login_tmdb(driver)
    print('ok:', ok, '| url:', driver.current_url, '| title:', driver.title)
    print(driver.execute_script("""
    const f = [...document.querySelectorAll('form#auth_login_form')].find(x => x.offsetParent);
    return {
      messages: [...document.querySelectorAll('.error, .errors, .alert, .notice, .flash, [role=alert], .message, .invalid-feedback')]
                .map(e => e.innerText.trim().slice(0, 200)).filter(Boolean),
      form_text: f ? f.innerText.trim().slice(0, 400) : 'no visible login form',
      hidden: f ? [...f.querySelectorAll('input[type=hidden]')].map(i => i.name + '=' + (i.value ? 'len' + i.value.length : 'EMPTY')) : [],
      username_len: f ? f.querySelector('[name=username]').value.length : null,
      iframes: [...document.querySelectorAll('iframe')].map(x => x.src.slice(0, 100) + ' visible=' + !!x.offsetParent),
    };
    """))


def main():
    global DRY_RUN, MAX_ROWS, FILL_FIELDS

    parser = argparse.ArgumentParser(description='Primary facts into TMDb (selenium-tmdb-deathday.ipynb as a script).')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--diagnostic', nargs='?', type=int, const=1265047, metavar='PERSON_ID',
                        help='read-only: the primary facts fields of one person (default: 1265047)')
    action.add_argument('--reset-cursor', action='store_true',
                        help='the next real run starts at the top of the latest export')
    action.add_argument('--debug-login', action='store_true',
                        help='inspect the login page, then log in and report')
    parser.add_argument('--dry-run', action='store_true',
                        help='pages checked, nothing saved')
    parser.add_argument('--max-rows', type=int, default=0, help='records per run, 0 for no limit (default: 0)')
    parser.add_argument('--fields', nargs='+', default=['deathday', 'birthday', 'gender'], metavar='FIELD',
                        help='fields to fill (default: deathday birthday gender)')
    args = parser.parse_args()

    if args.reset_cursor:
        # Cell 9
        # Reset the cursor: the next real run starts at the top of the latest export.
        set_store_value(PRIMARY_FACTS_DATASET['store_key'], {})
        return

    driver = None
    try:
        if args.debug_login:
            # The login is what is under test: a browser without the login of cell 5.
            driver = init_driver()
            debug_login(driver)
            return

        # Cell 5
        download_new_csv_files(PRIMARY_FACTS_DATASET['remote_folder'], PRIMARY_FACTS_DATASET['local_folder'])

        driver = init_driver()
        login_tmdb(driver)

        if args.diagnostic is not None:
            # Cell 6
            # Diagnostic (read-only, no write to TMDB): the primary facts fields of one person.
            debug_primary_facts_page(driver, args.diagnostic)
            return

        # Cell 7, its three settings taken from the command line
        DRY_RUN = args.dry_run
        MAX_ROWS = args.max_rows
        FILL_FIELDS = list(args.fields)
        driver = process_primary_facts(driver)

        # Cell 8
        # Loop is finished so we display the home page
        open_page(driver, 'https://www.themoviedb.org/')
    finally:
        close_browser_when_done(driver)


if __name__ == '__main__':
    main()
