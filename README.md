# selenium-tmdb

Selenium-driven automation that repairs missing `wikidata_id` external IDs on
[themoviedb.org](https://www.themoviedb.org/) records (movies, TV series, persons).

The repair list is computed off-site by the [preprocess/](preprocess/) pipeline,
which runs inside a Docker container on a VPS, queries the MariaDB database
that backs the CitizenPhil application, and emits one date-stamped CSV per
entity type. The notebooks in this repository pull those CSVs over SFTP, then
drive a real Chrome session to apply the fix.

---

## How it works

```
+----------------------------------+        SFTP        +-------------------------------+
| VPS (Docker container)           |   ------------>    | Local workstation             |
|                                  |   CSV files        |                               |
|  preprocess/selenium-tmdb.py     |                    | selenium-tmdb-wikidata_id*.ipynb |
|    -> runs *.sql against MariaDB |                    |   -> downloads CSV via SFTP   |
|    -> writes one CSV per query   |                    |   -> logs in to TMDB          |
|       in wikidata-id-*-fix/      |                    |   -> updates wikidata_id      |
+----------------------------------+                    +-------------------------------+
```

1. The VPS-side container (see [preprocess/README.md](preprocess/README.md))
   executes three SQL queries that find TMDB records whose `ID_WIKIDATA` is
   empty or invalid while a matching Wikidata record exists for the same IMDb
   ID, and writes the result to:
   - `wikidata-id-movie-fix/wikidata-id-movie-fix-YYYYMMDD.csv`
   - `wikidata-id-serie-fix/wikidata-id-serie-fix-YYYYMMDD.csv`
   - `wikidata-id-person-fix/wikidata-id-person-fix-YYYYMMDD.csv`
2. The notebooks in this repo connect to that VPS over SFTP, mirror the three
   folders into `./data/`, pick the most recently modified CSV per entity, and
   iterate through its rows.
3. For each row the notebook navigates Chrome to the TMDB edit page,
   `https://www.themoviedb.org/{movie|tv|person}/{id}/edit?active_nav_item=external_ids`,
   creates the English translation if missing, fills in the `wikidata_id`
   field, and clicks **Save**. If a duplicate Wikidata ID is detected
   (`ID_*_ERASE_WIKIDATA_ID`), the conflicting record is cleared first.
4. Records whose `wikidata_id` field is locked are skipped. Progress is
   persisted via the IPython `%store` magic so the loop can resume where it
   stopped after a browser crash, manual interrupt, or rate limit.

---

## Repository layout

| Path | Purpose |
| --- | --- |
| [selenium-tmdb-wikidata_id.ipynb](selenium-tmdb-wikidata_id.ipynb) | Unified notebook that processes movies, series and persons in one run via a `DATASETS` config block. |
| [selenium-tmdb-wikidata_id-movies01.ipynb](selenium-tmdb-wikidata_id-movies01.ipynb) | Standalone notebook for movies. |
| [selenium-tmdb-wikidata_id-series01.ipynb](selenium-tmdb-wikidata_id-series01.ipynb) | Standalone notebook for TV series. |
| [selenium-tmdb-wikidata_id-persons01.ipynb](selenium-tmdb-wikidata_id-persons01.ipynb) | Standalone notebook for persons. |
| [preprocess/](preprocess/) | Dockerised VPS-side job that produces the CSV input. See its own [README](preprocess/README.md). |
| [data/](data/) | Downloaded CSVs + `selenium-tmdb-wikidata_id.log` (git-ignored). |
| [doc/](doc/) | Reserved for additional documentation. |
| [requirements.txt](requirements.txt) | Python dependencies for the notebooks. |
| [.env.example](.env.example) | Template for the local `.env` file. |

---

## Prerequisites

- Python 3.10+
- Google Chrome installed locally (the matching ChromeDriver is fetched
  automatically by `webdriver-manager`).
- Jupyter / JupyterLab to run the notebooks interactively.
- A TMDB account with edit rights.
- SFTP access to the VPS that runs the [preprocess/](preprocess/) job.

---

## Installation

```bash
git clone https://github.com/<your-org>/selenium-tmdb.git
cd selenium-tmdb

python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

The dependencies are:

- `pandas` — CSV parsing.
- `python-dotenv` — loads `.env` credentials.
- `selenium` + `webdriver-manager` — Chrome automation.
- `paramiko` — SFTP download of the preprocess CSVs.

---

## Configuration

Copy [.env.example](.env.example) to `.env` at the repo root and fill in the
real values:

```dotenv
# TMDB account used to log in via Selenium
TMDB_LOGIN=your_tmdb_login
TMDB_PASSWORD=your_tmdb_password

# VPS hosting the preprocess Docker container
SFTP_HOST=your_sftp_host
SFTP_PORT=22
SFTP_LOGIN=your_sftp_login
SFTP_FOLDER=/home/debian/docker/selenium-tmdb

# Server verification (WinSCP SshHostKeyFingerprint format)
SFTP_SSHHOSTKEYFINGERPRINT=ssh-ed25519 256 SHA256:your_base64_digest

# First choice: SSH public-key authentication (both optional)
SFTP_KEY=
SFTP_KEY_PASSPHRASE=

# Second choice: password authentication (leave empty to disable)
SFTP_PASSWORD=
```

`SFTP_HOST`, `SFTP_LOGIN` and `SFTP_FOLDER` are the only mandatory SFTP
variables. `SFTP_FOLDER` must point to the directory that contains the
`wikidata-id-movie-fix/`, `wikidata-id-serie-fix/` and
`wikidata-id-person-fix/` subfolders produced by the preprocess job.

`.env` is git-ignored — never commit credentials.

### SFTP authentication

The notebook tries two authentication methods, in this order:

1. **SSH public key** (first choice) — `SFTP_LOGIN` plus a private key. The key
   is looked up in this order: `SFTP_KEY`, then the `IdentityFile` declared for
   `SFTP_HOST` in `~/.ssh/config` (`IdentitiesOnly yes` is honoured, so the
   server is not offered every key on the machine), then the default
   `~/.ssh/id_*` files, then any running SSH agent. If the key is
   passphrase-protected, the notebook uses `SFTP_KEY_PASSPHRASE` when set and
   otherwise prompts for it once — keeping the passphrase out of `.env` and out
   of the notebook output.
2. **Password** (second choice) — used only when `SFTP_PASSWORD` is set, and
   only after key authentication has failed.

In both cases the server itself is verified against
`SFTP_SSHHOSTKEYFINGERPRINT`, using the same value format as WinSCP's
`SessionOptions.SshHostKeyFingerprint` so it can be shared with the PowerShell
scripts. A mismatch aborts the connection immediately and is never retried with
the password. Accepted shapes:

```
ssh-ed25519 256 SHA256:<base64>
ssh-ed25519 256 <base64>
SHA256:<base64>
ssh-rsa 2048 aa:bb:…:ff          # MD5
```

If `SFTP_SSHHOSTKEYFINGERPRINT` is left empty the notebook prints a warning and
falls back to `~/.ssh/known_hosts`.

### Secrets and Docker

The notebooks at the repo root run locally and read `.env` directly. The
[preprocess/](preprocess/) job, by contrast, runs in a Docker container on the
VPS, and its secrets are **never** baked into the image:

- `preprocess/.dockerignore` excludes `.env` from the build context.
- `preprocess/Dockerfile` does not `COPY` `.env` and uses no secret-bearing
  `ENV` lines.
- `preprocess/selenium-tmdb.sh` injects secrets at runtime via
  `--env-file /home/debian/docker/selenium-tmdb/.env`, reading a
  host-managed file that lives outside the app source tree.

See [preprocess/README.md](preprocess/README.md) for the full policy.

---

## Running the notebooks

Open Jupyter and execute the notebook of your choice:

```bash
jupyter lab
```

### Unified notebook — recommended

[selenium-tmdb-wikidata_id.ipynb](selenium-tmdb-wikidata_id.ipynb) ingests all
three entity types in a single pass:

1. **Cells 0–1** — imports and credential check (raises `ValueError` if the
   `.env` is incomplete).
2. **Cell 2** — defines `DATASETS`, the per-entity config (CSV folder name,
   ID column, TMDB URL fragment, `%store` key, etc.).
3. **Cell 3** — pure-function helpers: `download_new_csv_files`,
   `get_latest_csv`, `set_wikidata_id`, `clear_wikidata_id`, `process_dataset`,
   etc.
4. **Cell 4** — downloads new CSVs for every dataset, then launches Chrome and
   logs into TMDB, declining the cookie banner on the way (it is anchored over
   the Save button).
5. **Cell 5** — runs `process_dataset` for movies, series, then persons. Each
   call returns the driver it ends up using and the cell rebinds it
   (`driver = process_dataset(driver, ...)`), because a crashed Chrome is
   replaced mid-run by a fresh, logged-in one.
6. **Last cell** — navigates Chrome back to the home page when done.

### Entity-specific notebooks

`selenium-tmdb-wikidata_id-movies01.ipynb`,
`selenium-tmdb-wikidata_id-series01.ipynb` and
`selenium-tmdb-wikidata_id-persons01.ipynb` are older single-entity variants of
the same workflow, useful when you want to retry one type independently. They
share the resumable `%store` cursor with the unified notebook (`lngmovieidstart`,
`lngserieidstart`, `lngpersonidstart`).

### Resuming after an interruption

Each iteration writes the last processed ID to the IPython store:

```python
%store lngmovieidstart    # also lngserieidstart, lngpersonidstart
```

Re-running cell 2 of the legacy notebooks (or restarting the unified notebook)
loads the cursor with `%store -r` and the loop skips everything already done.

### When Chrome crashes

Long runs lose the browser in two ways, and they do not look alike.

A hard crash makes the next Selenium command raise: `tab crashed`, `invalid
session id`, `chrome not reachable`, or, when chromedriver simply stops
answering, a raw `ReadTimeoutError: HTTPConnectionPool(host='localhost',
port=...)`.

A renderer that runs out of memory raises nothing at all. Chrome replaces the
page with its own "Aw, Snap!" document, `driver.get()` returns normally and every
command keeps working, so a loop watching only for exceptions walks the rest of
the CSV finding no `wikidata_id` field, writing nothing and advancing the cursor
past every record it touches. A run on 2026-09-04 did exactly that for ten
minutes before it was noticed.

The notebook handles both:

- `get_chrome_error_code()` recognises Chrome's own error page: `document.URL`
  becomes `chrome-error://chromewebdata/` (while `driver.current_url` still
  reports the URL that was requested), the body class is `neterror`, and the page
  displays the code (`Out of Memory`, `ERR_NAME_NOT_RESOLVED`). `open_page()`
  raises `BrowserSessionLost` on such a page instead of returning, so the record
  is retried on a fresh browser rather than skipped.
- `is_browser_gone()` covers the hard crash: invalid session, chrome not
  reachable, tab crashed, any urllib3 read timeout. Ordinary Selenium errors, a
  missing element or a slow page, still propagate untouched.
- Either way the record is retried on a fresh Chrome, up to
  `BROWSER_RESTART_ATTEMPTS` (3) times. `restart_browser()` closes the old
  session, killing chromedriver if `quit()` hangs, starts a new driver and logs
  back into TMDB. Solve the CAPTCHA in the new window if TMDB shows one.
- A TMDB session that expired silently is handled the same way: the edit page
  redirects to the login form, which raises `BrowserSessionLost` instead of
  counting the record as processed.
- As a backstop, `MAX_CONSECUTIVE_SKIPS` (8) records in a row writing nothing
  restarts the browser once, and stops the run if it happens again. Over the 1061
  records of the run before that incident, 1046 were written and the longest run
  without a write was 1, so the threshold sits far above normal.
- The client timeout is 60 s and the page load timeout 45 s, so a dead browser is
  noticed in one minute instead of two, and a merely slow page raises an ordinary
  `TimeoutException`.
- When every attempt fails the run stops, the stored cursor still pointing at the
  last record actually written, so re-running the cell resumes there.

### Keeping Chrome from running out of memory

Every TMDB page is same-site, so Chrome serves the whole run from a single
renderer whose memory only grows. Measured over the same 12 navigations:

| Chrome as configured | renderer RSS | growth |
| --- | --- | --- |
| default flags | 310 to 502 MB | 16 MB per page |
| `--disable-features=BackForwardCache` | 290 to 398 MB | 9 MB per page |
| the same, plus the memory purge | 300 to 352 MB | 4.3 MB per page |

The notebook applies both. `build_chrome_options()` turns off the back/forward
cache, which otherwise keeps every previous page alive inside that one renderer,
and `purge_browser_memory()` sends `Memory.forciblyPurgeJavaScriptMemory` between
records. Neither reclaims everything, so `BROWSER_RECYCLE_EVERY` (250) restarts
the browser regularly on top of them. Raise it if the extra logins get in the
way, set it to `0` to turn recycling off.

---

## CSV schema

Each CSV is `;`-separated with `"`-quoted fields. The columns used by the
notebooks are:

| Column | Description |
| --- | --- |
| `ID_MOVIE` / `ID_SERIE` / `ID_PERSON` | TMDB numeric ID to update. |
| `ID_WIKIDATA` | Target Wikidata ID (`Q12345`) to write into TMDB. |
| `ID_IMDB` | IMDb ID used to match TMDB and Wikidata records (informational). |
| `ID_*_ERASE_WIKIDATA_ID` | TMDB ID of a conflicting record whose `wikidata_id` must be cleared before the fix. May be empty/`NaN`. |
| `TITLE` / `NAME` | Display label (informational). |
| `ADULT` | Adult-content flag (informational). |

See the SQL queries in [preprocess/](preprocess/) for the exact join logic that
produces these rows.

---

## Logs

The unified notebook appends one line per successful update to
`data/selenium-tmdb-wikidata_id.log`:

```
<entity>;<tmdb_id>;<wikidata_id>
```

This file is git-ignored (`*.log`) and can be tailed during a run.

---

## Troubleshooting

- **`ValueError: Missing SFTP/TMDB configuration`** — your `.env` is missing one
  of the mandatory variables (`SFTP_HOST`, `SFTP_LOGIN`, `SFTP_FOLDER`,
  `TMDB_LOGIN`, `TMDB_PASSWORD`). Copy from `.env.example`.
- **`SSH host key fingerprint mismatch` / `SSH host key type mismatch`** — the
  server key does not match `SFTP_SSHHOSTKEYFINGERPRINT`. The error prints both
  the presented and the expected digest: update the `.env` only if you know why
  the VPS host key changed, otherwise treat it as a failed verification.
- **`SFTP SSH key authentication failed`** — no usable private key was found for
  `SFTP_LOGIN`. Check `SFTP_KEY` or the `IdentityFile` entry for `SFTP_HOST` in
  `~/.ssh/config`, and supply the passphrase at the prompt (or via
  `SFTP_KEY_PASSPHRASE`) if the key is protected. Setting `SFTP_PASSWORD` gives
  you the password fallback.
- **`FileNotFoundError: No file found matching ...`** — the SFTP download
  returned no files. Check that the preprocess container ran today on the VPS
  (see [preprocess/README.md](preprocess/README.md)) and that `SFTP_FOLDER` is
  correct.
- **TMDB login loops / CAPTCHA** — TMDB occasionally challenges the headed
  Chrome session. Solve it manually in the open window; the login waits for the
  browser to leave `/login`, prints a reminder while the challenge is pending
  and carries on as soon as it is solved.
- **`ReadTimeoutError: HTTPConnectionPool(host='localhost', port=...)`**: Chrome
  or chromedriver died under the loop. The notebook restarts the browser, logs
  back in and retries the record by itself, up to three times, as described in
  [When Chrome crashes](#when-chrome-crashes). If it gives up, the `%store`
  cursor still points at the last record written and re-running the cell resumes
  there.
- **Chrome shows "Aw, Snap!" / "Aïe aïe aïe" with `Out of Memory`**: the renderer
  exhausted its memory. Nothing raises in that state, which is why the notebook
  recognises the error page itself, restarts Chrome and retries the record. See
  [Keeping Chrome from running out of memory](#keeping-chrome-from-running-out-of-memory)
  for what makes it rarer.
- **Records skipped in bulk, nothing written**: the run stops by itself after 8
  records in a row write nothing. Check in the browser whether TMDB is showing an
  error page, a rate limit or a login form, then resume from the stored cursor.
- **Save seems to do nothing, or `ElementClickInterceptedException`**: TMDB's
  OneTrust cookie banner is anchored at the bottom of the window, right over the
  Save button of an edit page, and it takes the click. `login_tmdb()` clicks
  **Tout refuser** (`#onetrust-reject-all-handler`) on every fresh browser, which
  sets `OptanonAlertBoxClosed` for that profile; `click_save_button()` dismisses
  it and retries if a click is intercepted anyway, falling back to a scripted
  click. Since each restart starts from a clean profile, the banner is declined
  again every time.
- **"Element 'Locked' exists on the page."** — the `wikidata_id` field is
  locked by a TMDB moderator. The script intentionally skips it; no action
  needed.
- **Chrome / ChromeDriver mismatch** — `webdriver-manager` installs the right
  driver on the first run; delete `~/.wdm/` to force a re-download if Chrome
  has been upgraded.

---

## License

Released under the [MIT License](LICENSE). © 2025 Philippe Vaugouin.
