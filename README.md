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
|       in wikidata-id-*/          |                    |   -> updates wikidata_id      |
+----------------------------------+                    +-------------------------------+
```

1. The VPS-side container (see [preprocess/README.md](preprocess/README.md))
   executes three SQL queries that find TMDB records whose `ID_WIKIDATA` is
   empty or invalid while a matching Wikidata record exists for the same IMDb
   ID, and writes the result to:
   - `wikidata-id-movie-fix/wikidata-id-movie-fix-YYYYMMDD.csv`
   - `wikidata-id-serie-fix/wikidata-id-serie-fix-YYYYMMDD.csv`
   - `wikidata-id-person-fix/wikidata-id-person-fix-YYYYMMDD.csv`

   Three more queries find records whose `ID_WIKIDATA` is a valid QID but
   differs from Wikidata's, kept only when that QID names the TMDB record itself
   (`P4947`/`P4983`/`P4985`), and write `wikidata-id-<entity>-replace/wikidata-id-<entity>-replace-YYYYMMDD.csv`.
2. The notebooks in this repo connect to that VPS over SFTP, mirror the
   folders into `./data/`, pick the most recently modified CSV per dataset, and
   iterate through its rows.
3. For each row the notebook navigates Chrome to the TMDB edit page,
   `https://www.themoviedb.org/{movie|tv|person}/{id}/edit?active_nav_item=external_ids`,
   creates the English translation if missing, fills in the `wikidata_id`
   field, and clicks **Save**. If a duplicate Wikidata ID is detected
   (`ID_*_ERASE_WIKIDATA_ID`), the conflicting record is cleared first.
   Such a row is only exported when Wikidata itself names the record to fill
   (TMDb id property `P4947`/`P4983`/`P4985`); without that proof the QID stays
   where it is, otherwise two duplicate records would trade it on every run.
4. Records whose `wikidata_id` field is locked are skipped. Progress is
   persisted via the IPython `%store` magic so the loop can resume where it
   stopped after a browser crash, manual interrupt, or rate limit.

---

## Repository layout

| Path | Purpose |
| --- | --- |
| [selenium-tmdb-wikidata_id.ipynb](selenium-tmdb-wikidata_id.ipynb) | Unified notebook that processes movies, series and persons in one run via a `DATASETS` config block. |
| [selenium-tmdb-deathday.ipynb](selenium-tmdb-deathday.ipynb) | Fills the primary facts of TMDB persons (death and birth dates, gender, place of birth). |
| [selenium-tmdb-wikidata_id.py](selenium-tmdb-wikidata_id.py), [selenium-tmdb-deathday.py](selenium-tmdb-deathday.py) | The unified and the primary facts notebooks as terminal scripts (see [The same notebooks as scripts](#the-same-notebooks-as-scripts)). |
| [selenium-tmdb-wikidata_id-v2.py](selenium-tmdb-wikidata_id-v2.py), [selenium-tmdb-deathday-v2.py](selenium-tmdb-deathday-v2.py), [selenium_tmdb_common.py](selenium_tmdb_common.py) | The same two scripts on a shared library, driving a real Chrome on a persistent profile (see [v2 scripts](#v2-scripts-shared-library-real-chrome)). |
| [preprocess/](preprocess/) | Dockerised VPS-side job that produces the CSV input. See its own [README](preprocess/README.md). |
| [data/](data/) | Downloaded CSVs (git-ignored). |
| [logs/](logs/) | JSON Lines trace of every wikidata_id write, one file per day (git-ignored). |
| [doc/](doc/) | Additional documentation, e.g. [doc/tmdb-login-aws-waf/](doc/tmdb-login-aws-waf/README.md) (login blocked since 2026-11-06). |
| [archive/](archive/) | SQL tests of closed operations, with their results. |
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
SFTP_FOLDER=/home/debian/docker/selenium-tmdb/preprocess

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
`wikidata-id-<entity>-fix/` and `wikidata-id-<entity>-replace/` subfolders
produced by the preprocess job.

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
  `--env-file /home/debian/docker/selenium-tmdb/preprocess/.env`, reading a
  host-managed, git-ignored file kept out of the build context.

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

1. **Cells 1 and 2**: imports and credential check (raises `ValueError` if the
   `.env` is incomplete). Cell 0 is a commented-out `%pip install paramiko`.
2. **Cell 3**: defines `DATASETS`, six entries: the fill (`fix`) and the
   `replace` dataset of each entity, each with its CSV folder name, ID column,
   TMDB URL fragment, `%store` key, etc.
3. **Cell 4**: pure-function helpers: `download_new_csv_files`,
   `get_latest_csv`, `set_wikidata_id`, `clear_wikidata_id`, `process_dataset`,
   etc.
4. **Cell 5**: downloads new CSVs for every dataset, then launches Chrome and
   logs into TMDB, declining the cookie banner on the way (it is anchored over
   the Save button).
5. **Cell 6**: read-only diagnostic, `debug_wikidata_page`, which inspects one
   edit page without writing.
6. **Cell 7**: runs `process_dataset` for the movie, series, then person fill
   datasets (`DATASETS[0]` to `[2]`). Each call returns the driver it ends up
   using and the cell rebinds it (`driver = process_dataset(driver, ...)`),
   because a crashed Chrome is replaced mid-run by a fresh, logged-in one. The
   three `replace` datasets (`DATASETS[3]` to `[5]`) are not called by this
   cell: run them by hand the same way.
7. **Cell 8**: navigates Chrome back to the home page when done.
8. **Cell 9**: resets the six `%store` cursors to 0.

### The same notebooks as scripts

[selenium-tmdb-wikidata_id.py](selenium-tmdb-wikidata_id.py) and
[selenium-tmdb-deathday.py](selenium-tmdb-deathday.py) run the two notebooks
from a terminal, with the same virtual environment. The code cells up to the
helpers are copied verbatim; the cells that follow are chosen on the command
line (`--help` lists them):

```bash
python selenium-tmdb-wikidata_id.py                   # cells 5, 7, 8: the three fill datasets
python selenium-tmdb-wikidata_id.py --datasets 3 4 5  # the replace datasets
python selenium-tmdb-wikidata_id.py --diagnostic movie 300115
python selenium-tmdb-wikidata_id.py --reset-cursors

python selenium-tmdb-deathday.py --dry-run --max-rows 20
python selenium-tmdb-deathday.py                      # cell 7 as it stands: DRY_RUN off, deathday birthday gender
python selenium-tmdb-deathday.py --diagnostic 1265047
python selenium-tmdb-deathday.py --reset-cursor
```

What differs from Jupyter, and nothing else:

- `%store` does not exist outside IPython, so the scripts read and write the
  database it uses (`~/.ipython/profile_default/db`, keys `autorestore/<name>`).
  The cursors are shared: a run stopped in the notebook resumes in the script,
  and the other way round.
- The script moves to its own folder first, so `.env`, `data/` and `logs/` are
  the repository's wherever it is started from.
- Chrome stays open at the end until you press Enter, as it would after the
  last cell, then closes.

### v2 scripts: shared library, real Chrome

[selenium-tmdb-wikidata_id-v2.py](selenium-tmdb-wikidata_id-v2.py) and
[selenium-tmdb-deathday-v2.py](selenium-tmdb-deathday-v2.py) take the same
options as the scripts above. Two things differ:

- **The shared code lives in [selenium_tmdb_common.py](selenium_tmdb_common.py)**:
  SFTP, the cursor store, Chrome, login, crash recovery, the JSON Lines log.
  What only the wikidata_id robot uses (`set_wikidata_id`, `process_dataset`,
  ...) stays in its script.
- **Chrome is a real one, on a profile that persists.** The script starts
  Chrome itself, without the automation flag (`navigator.webdriver` is false),
  on `CHROME_PROFILE_DIR` with the DevTools port `CHROME_DEBUG_PORT`, and
  Selenium attaches to it. The TMDB session and the declined cookie banner stay
  in the profile: the first run asks you to log in by hand in that window if the
  `.env` credentials do not go through (10 minutes), and the next runs, and every
  crash restart or recycling, find the session open. At the end of a run Chrome
  stays open, and the next run attaches to it.

It cannot be your everyday Chrome profile: since Chrome 136 the DevTools port is
refused on the default profile. Your usual Chrome can stay open alongside, it is
a separate instance. While the robot's profile is open, any local program can
drive it through the port (127.0.0.1 only). If a run fails with `Chrome does not
answer on port 9222`, a window is open on that profile without the port: close
it and run again.

```dotenv
# Optional, v2 scripts only
CHROME_DEBUG_PORT=9222
CHROME_PROFILE_DIR=          # default %LOCALAPPDATA%\selenium-tmdb\chrome-profile
CHROME_BINARY=               # default: found in Program Files / LOCALAPPDATA
```

The older single-entity notebooks (`-movies01`, `-series01`, `-persons01`)
were removed on 2026-11-08; they remain in the git history.

### Resuming after an interruption

Each iteration writes the last processed ID to the IPython store:

```python
%store lngmovieidstart    # also lngserieidstart, lngpersonidstart
```

The unified notebook reads it back through `get_store_value`, one key per
dataset (`lngmovieidstart`, ..., `lngmoviereplaceidstart`, ...), and the
loop skips everything already done.

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

`build_chrome_options()` turns off the back/forward cache, which otherwise keeps
every previous page alive inside that one renderer. That does not reclaim
everything, so `BROWSER_RECYCLE_EVERY` (250) restarts the browser regularly on
top of it. Raise it if the extra logins get in the way, set it to `0` to turn
recycling off.

A CDP purge between records (`Memory.forciblyPurgeJavaScriptMemory`) brought
the growth down to 4.3 MB per page until Chrome 153. It was removed on
2026-10-10: since Chrome 154, every navigation after the first purge hangs (see
Troubleshooting).

### Where the time goes (primary facts robot)

Measured on 2026-11-06 from the timestamps of the
`logs/selenium-tmdb-deathday-*.log` lines of 2026-11-03 to 2026-11-06, about
21,000 persons and 28,000 fields saved. Median per person: **7.0 s**.

| Phase | Time | What it is |
| --- | --- | --- |
| `PAUSE_BETWEEN_ROWS` | 5.0 s | the deliberate pause after each person, 70% of the run (2 s since 2026-11-08) |
| open the page and check the fields | about 0.7 s | `open_primary_facts_patiently` and the reads before writing |
| write, Save, reload, read back | about 1.1 s | includes a second full page load, used only to confirm |

The split between the two TMDb phases rests on the few persons where one field
was skipped and another saved: an order of magnitude, not an exact figure.

The pause has since come down. The run of 2026-11-08 (v2 script, real Chrome),
with `PAUSE_BETWEEN_ROWS = 1`, took a median **4.0 s** per person (3.8 to 4.4 s
for 9 persons in 10, over 1,250 persons), so about 3 s of TMDb work. Philippe
then set the pause to **2 s** (2026-11-08): expect about 5 s per person.

- **The network.** The work per person outside the pause was 1.3 to 1.6 s up to
  the morning of 2026-11-04, then 5 to 11 s (up to 36% of persons above 10 s)
  once NordVPN was on, then a stable 3.5 s. A single TCP connection to
  themoviedb.org took 94 to 430 ms through the NordVPN exit, against 10 to 20 ms
  normally. A strong correlation, not a proof: no run was measured with NordVPN
  off.
- **The throttle counts persons, not a rate.** Every run got its first 429
  after 1,530 to 1,630 persons, whether it lasted 3 h or 7 h and wrote 1,880 or
  2,380 fields. The pause does not buy extra quota, it only delays the 429.
  Never work around it (a new session to reset the counter): the ceiling is
  TMDb's.

Ways to go faster, biggest gain first:

1. Lower `PAUSE_BETWEEN_ROWS`: done, 5 s down to 2 s on 2026-11-08 (1 s was
   tried the same morning). Philippe's call, not a default: the pause is there
   to be gentle with TMDb, so do not lower it further without asking.
2. Take the robot's Chrome out of NordVPN (split tunneling on `chrome.exe`, or a
   faster server): about 2 s per person on the measured days.
3. Block images and ads in `build_chrome_options`: untested, needs a dry run
   first, since the Kendo widgets of the edit page must keep working.
4. Dropping the confirmation reload would save about a third of the work time.
   Do not: that read-back caught 25 saves that had not taken, and it is what
   makes a logged `success` true on TMDb.

For an exact split per phase, a `timings` field (open, check, write, save,
reload) could be added to each `primary_fact_write` event; it has not been.

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

The unified notebook writes one **JSON object per line** (JSON Lines) to a file
per day, `logs/selenium-tmdb-wikidata_id-YYYYMMDD.log`. The folder is created on
first write and is git-ignored.

The unit of the trace is the **write attempt**, not the successful write: a
record TMDB refuses (locked field, 404, missing English translation, save not
confirmed) gets its line too, which is what makes a run readable afterwards.

```json
{"schema":1,"ts":"2026-09-14T18:32:07.412+02:00","run_id":"20260914T163021Z-a3f1c2","event":"wikidata_id_write","action":"set","outcome":"success","reason":null,"dataset":"movies","mode":"fix","entity":"movie","tmdb_id":300115,"wikidata_id":"Q644554","previous_wikidata_id":null,"changed":true,"url":"https://www.themoviedb.org/movie/300115/edit?active_nav_item=external_ids","csv_file":"wikidata-id-movie-fix-20260913.csv","csv_row":42,"attempt":1,"duration_ms":4210}
```

| Field | Meaning |
| --- | --- |
| `event` | `wikidata_id_write`, or the `dataset_start` / `dataset_end` pair that frames each dataset and carries the row count and the final counters. |
| `action` | `set`, or `clear` when a QID is erased from a conflicting record before the fix. |
| `outcome` | `success`, `skipped` (TMDB refused the record) or `failed` (the write was attempted and did not stick). |
| `reason` | `page_load_timeout`, `page_not_found`, `translation_failed`, `field_not_found`, `locked`, `field_not_editable`, `field_write_refused`, `save_not_confirmed`, `session_lost`. Null on success. |
| `mode` | `fix` or `replace`, from the `DATASETS` entry. |
| `previous_wikidata_id` | The value on the page before the field was cleared. On a `replace` run, the only record of what was overwritten. |
| `changed` | True only when a success actually altered the value. |
| `csv_file` / `csv_row` | The export and row the record came from. |
| `attempt` | Browser-restart retry number, so one record retried is not read as two. |
| `run_id` | Minted when the helpers cell runs; groups the lines of one session across the six datasets. |

Reading it back:

```bash
# every real modification of the day
jq -c 'select(.event=="wikidata_id_write" and .outcome=="success" and .changed)' logs/*.log
# why records were refused, most frequent first
jq -r 'select(.event=="wikidata_id_write" and .outcome!="success") | .reason' logs/*.log | sort | uniq -c | sort -rn
# what a replace run overwrote
jq -r 'select(.mode=="replace" and .outcome=="success") | [.tmdb_id,.previous_wikidata_id,.wikidata_id] | @tsv' logs/*.log
```

Writing the log never aborts a run: a failure to write is printed and swallowed.

`data/selenium-tmdb-wikidata_id.log`, the previous `<entity>;<tmdb_id>;<wikidata_id>`
file, is no longer written. It recorded successes only. Its history stays on disk.

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
- **`PermissionError: [WinError 10013]` on the SFTP connection, with NordVPN
  on** (2026-11-04): NordVPN refuses all local traffic to Tailscale addresses
  (`100.64.0.0/10`, the range its own Meshnet uses), so the VPS is unreachable
  over Tailscale although `tailscale ping` answers and the rest of the Internet
  works. It is not Python: PowerShell fails the same way. To keep NordVPN, in
  its app: turn **Meshnet** off first, then if needed allow LAN visibility and
  exclude `tailscaled.exe` (and the venv's `python.exe`) through **split
  tunneling**. Alternatively point `SFTP_HOST` in `.env` at the VPS's public
  address: `SFTP_SSHHOSTKEYFINGERPRINT` still guarantees it is the same server,
  but SSH then crosses the Internet, and a source-IP filter on the VPS could one
  day refuse a NordVPN exit address. NordVPN also slows TMDb pages down (see
  [Where the time goes](#where-the-time-goes-primary-facts-robot)).
- **`FileNotFoundError: No file found matching ...`** — the SFTP download
  returned no files. Check that the preprocess container ran today on the VPS
  (see [preprocess/README.md](preprocess/README.md)) and that `SFTP_FOLDER` is
  correct.
- **TMDB login loops / CAPTCHA** — TMDB occasionally challenges the headed
  Chrome session. Solve it manually in the open window; the login waits for the
  browser to leave `/login`, prints a reminder while the challenge is pending
  and carries on as soon as it is solved.
- **Login never confirmed, no CAPTCHA, manual login works**: since 2026-11-06
  the `/login` page carries every auth form twice (the page and a hidden copy in
  the header) plus a signup form with fields of the same names, and pressing
  Enter in the password field no longer logs in. `login_tmdb()` now fills the
  *visible* login form (`find_login_fields`) and clicks its own submit button
  (`submit_login_form`), matched on `type="submit"` because the label follows the
  account language.
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
- **`wikidata_id field not found`, on a page that is neither 404 nor locked**:
  the record has no English translation, so TMDB redirects the edit URL to
  `/translate/<entity>/<id>-<slug>`, a page with no edit form. The script clicks
  the **Create Translation** button there and comes back to the edit page.
  Matching that button on its text alone matters: its icon span is
  `glyphicons plus svg` on the translate page and `glyphicons_v2 plus svg`
  elsewhere, and the class-based XPath used until 2026-09-07 matched neither,
  which silently turned 25 of 65 movie records into skips.
- **Records failing with `page_load_timeout` while the page looks loaded, 135 s
  each, except the first one after every Chrome start**: the page draws, but
  chromedriver never sees the load end, so `driver.get()` and the next two
  commands each wait the full 45 s. The trigger was the CDP memory purge the
  loop sent between records: harmless up to Chrome 153, it left every later
  navigation hanging from Chrome 154 on (first seen 2026-10-08, 94 timeouts for
  13 writes). The purge was removed on 2026-10-10. Switching to the `eager` page
  load strategy did not help, which is how the load event was ruled out. If the
  symptom comes back after a Chrome update, look first for any CDP call made
  between navigations.
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
