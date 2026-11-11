# selenium-tmdb

Selenium-driven automation that repairs missing `wikidata_id` external IDs on
[themoviedb.org](https://www.themoviedb.org/) records (movies, TV series, persons).

The repair list is computed off-site by the [preprocess/](preprocess/) pipeline,
which runs inside a Docker container on a VPS, queries the MariaDB database
that backs the CitizenPhil application, and emits one date-stamped CSV per
entity type. The Python scripts in this repository pull those CSVs over SFTP,
then drive a real Chrome session to apply the fix. Each one has a `.bat`
launcher for Windows.

---

## How it works

```
+----------------------------------+        SFTP        +-------------------------------+
| VPS (Docker container)           |   ------------>    | Local workstation             |
|                                  |   CSV files        |                               |
|  preprocess/selenium-tmdb.py     |                    | selenium-tmdb-*-v2.py         |
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

   Since 2026-11-11 three more, `external-ids-<entity>-fix.sql`, list the
   external ids (Facebook, Instagram, X, plus TikTok and YouTube for persons, IMDb,
   and TheTVDB for series) empty on TMDB while Wikidata has one clean value, the
   QID proven to be the record. Social ids are proposed only for records
   `tmdb-crawler` has read since its 1.0.12 (`TIM_EXTERNAL_IDS`): before, the
   crawler did not keep them, so an empty one meant nothing. First measure, before
   that crawler had read any record: 11,868 series (11,806 TheTVDB ids, 106 IMDb),
   137 movies and 469 persons (IMDb ids), 46 to 134 s per query.
2. The scripts in this repo connect to that VPS over SFTP, mirror the
   folders into `./data/`, pick the most recently modified CSV per dataset, and
   iterate through its rows.
3. For each row the script navigates Chrome to the TMDB edit page,
   `https://www.themoviedb.org/{movie|tv|person}/{id}/edit?active_nav_item=external_ids`,
   creates the English translation if missing, fills in the `wikidata_id`
   field, and clicks **Save**. If a duplicate Wikidata ID is detected
   (`ID_*_ERASE_WIKIDATA_ID`), the conflicting record is cleared first.
   Such a row is only exported when Wikidata itself names the record to fill
   (TMDb id property `P4947`/`P4983`/`P4985`); without that proof the QID stays
   where it is, otherwise two duplicate records would trade it on every run.
4. Records whose `wikidata_id` field is locked are skipped. Progress is
   persisted in the IPython `%store` database so the loop can resume where it
   stopped after a browser crash, manual interrupt, or rate limit.

---

## Repository layout

| Path | Purpose |
| --- | --- |
| [selenium-tmdb-wikidata_id.bat](selenium-tmdb-wikidata_id.bat), [selenium-tmdb-deathday.bat](selenium-tmdb-deathday.bat) | Windows launchers of the two v2 scripts, through `uv` (see [Running the scripts](#running-the-scripts)). |
| [selenium-tmdb-wikidata_id-v2.py](selenium-tmdb-wikidata_id-v2.py) | Writes Wikidata QIDs into the `wikidata_id` of movies, series and persons, through the six `DATASETS` entries. |
| [selenium-tmdb-deathday-v2.py](selenium-tmdb-deathday-v2.py) | Fills the primary facts of TMDB persons (death and birth dates, gender, place of birth). |
| [selenium_tmdb_common.py](selenium_tmdb_common.py) | Code shared by the two v2 scripts: SFTP, cursor store, real Chrome, login, crash recovery, JSON Lines log. |
| [selenium-tmdb-wikidata_id.py](selenium-tmdb-wikidata_id.py), [selenium-tmdb-deathday.py](selenium-tmdb-deathday.py) | v1 scripts: the former notebooks copied as they were, with a disposable Chrome (see [v1 scripts](#v1-scripts)). |
| [preprocess/](preprocess/) | Dockerised VPS-side job that produces the CSV input. See its own [README](preprocess/README.md). |
| [data/](data/) | Downloaded CSVs (git-ignored). |
| [logs/](logs/) | JSON Lines trace of every wikidata_id write, one file per day (git-ignored). |
| [doc/](doc/) | Additional documentation. |
| [archive/](archive/) | SQL tests of closed operations with their results, and the former Jupyter notebooks (archived 2026-11-08). |
| [requirements.txt](requirements.txt) | Python dependencies of the scripts. |
| [.env.example](.env.example) | Template for the local `.env` file. |

---

## Prerequisites

- Python 3.10+
- Google Chrome installed locally (the matching ChromeDriver is fetched
  automatically by `webdriver-manager`).
- [uv](https://docs.astral.sh/uv/), which the `.bat` launchers use (or a plain
  virtual environment, see below).
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

With uv there is nothing to install by hand: `uv run --with-requirements
requirements.txt` (what the `.bat` launchers run) uses the `.venv` of the folder
when it has everything, and otherwise builds the environment from
`requirements.txt`.

The dependencies are:

- `pandas` — CSV parsing.
- `python-dotenv` — loads `.env` credentials.
- `selenium` + `webdriver-manager` — Chrome automation.
- `paramiko` — SFTP download of the preprocess CSVs.
- `ipython` — the `%store` database that keeps the resume cursors.

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

The scripts try two authentication methods, in this order:

1. **SSH public key** (first choice) — `SFTP_LOGIN` plus a private key. The key
   is looked up in this order: `SFTP_KEY`, then the `IdentityFile` declared for
   `SFTP_HOST` in `~/.ssh/config` (`IdentitiesOnly yes` is honoured, so the
   server is not offered every key on the machine), then the default
   `~/.ssh/id_*` files, then any running SSH agent. If the key is
   passphrase-protected, the script uses `SFTP_KEY_PASSPHRASE` when set and
   otherwise prompts for it once in the terminal — keeping the passphrase out of
   `.env` and out of the output.
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

If `SFTP_SSHHOSTKEYFINGERPRINT` is left empty the script prints a warning and
falls back to `~/.ssh/known_hosts`.

### Secrets and Docker

The scripts at the repo root run locally and read `.env` directly. The
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

## Running the scripts

Double-click a launcher, or start it from a command prompt to pass options:

| Launcher | Script | What it does |
| --- | --- | --- |
| [selenium-tmdb-wikidata_id.bat](selenium-tmdb-wikidata_id.bat) | `selenium-tmdb-wikidata_id-v2.py` | wikidata_id of movies, series, persons |
| [selenium-tmdb-deathday.bat](selenium-tmdb-deathday.bat) | `selenium-tmdb-deathday-v2.py` | primary facts of persons |

Each launcher moves to its own folder, wherever the repository sits on the
machine, runs the script through `uv run --with-requirements requirements.txt`,
passes on any option given to it, then waits for a key, so the run's output
stays on screen when it was started by a double-click. The options:

```bat
selenium-tmdb-wikidata_id.bat                    :: the three fill datasets (movies, series, persons)
selenium-tmdb-wikidata_id.bat --datasets 3 4 5   :: the three replace datasets
selenium-tmdb-wikidata_id.bat --diagnostic movie 300115   :: read-only
selenium-tmdb-wikidata_id.bat --reset-cursors

selenium-tmdb-deathday.bat --dry-run --max-rows 20   :: pages checked, nothing saved
selenium-tmdb-deathday.bat                           :: real run: deathday birthday gender
selenium-tmdb-deathday.bat --fields deathday birthday gender place_of_birth
selenium-tmdb-deathday.bat --diagnostic 1265047      :: read-only
selenium-tmdb-deathday.bat --reset-cursor
```

`--help` lists them. Without `--dry-run`, the primary facts script writes on
TMDB. Without a launcher: `uv run --with-requirements requirements.txt python
selenium-tmdb-deathday-v2.py ...`, or the `.venv`'s `python`.

The resume cursors live in the database of the IPython `%store` magic
(`~/.ipython/profile_default/db`, keys `autorestore/<name>`), which the scripts
read and write directly, without Jupyter. They are the cursors the notebooks
used, so the switch to scripts lost no progress.

### v2 scripts: shared library, real Chrome

[selenium-tmdb-wikidata_id-v2.py](selenium-tmdb-wikidata_id-v2.py) and
[selenium-tmdb-deathday-v2.py](selenium-tmdb-deathday-v2.py), the scripts the
launchers run, differ from the v1 scripts in two ways:

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
# Primary facts robot (v2): pause between persons, read again every 15 minutes
PAUSE_BETWEEN_ROWS=2
```

### v1 scripts

[selenium-tmdb-wikidata_id.py](selenium-tmdb-wikidata_id.py) and
[selenium-tmdb-deathday.py](selenium-tmdb-deathday.py) are the former notebooks
copied as they were (same options as v2), each carrying its own copy of the
helpers, with a disposable Chrome that chromedriver starts on an empty profile
and logs in again at every start. At the end of a run that Chrome stays open
until you press Enter.

The Jupyter notebooks they came from, `selenium-tmdb-wikidata_id.ipynb` and
`selenium-tmdb-deathday.ipynb`, are in [archive/](archive/) since 2026-11-08,
with the output of their last runs. The single-entity notebooks (`-movies01`,
`-series01`, `-persons01`) were removed the same day; they remain in the git
history.

### Resuming after an interruption

Each iteration writes the last processed ID to the `%store` database through
`set_store_value`, and the next run reads it back through `get_store_value`,
one key per dataset (`lngmovieidstart`, ..., `lngmoviereplaceidstart`, ...;
`primaryfactscursor` for the primary facts, a CSV file name and row): the loop
skips everything already done.

The primary facts cursor also keeps the fields of the run that stored it (since
1.0.20; an older cursor counts as `deathday birthday gender`). A run asking for a
field that run did not cover, `--fields place_of_birth` after the dates, starts
at the top of the export instead of resuming at the end of a CSV already walked,
where it would write nothing; the fields already written stay skipped, read back
from the logs.

**Place of Birth is a place of TMDb's list, not free text.** The field is a Kendo
AutoComplete fed by `/search/remote/place`; choosing a suggestion fills the hidden
`place_of_birth_id`, and text typed without that id is dropped on Save. Until
1.0.20 the robot typed the text, so every place came back `save_not_confirmed`.
It now runs the page's own search (read-only, a dry run does it too) and picks
the suggestion whose name is exactly the export's value. With no exact match it
leaves the field alone (`place_not_found`, not retried on later runs) and never
uses **Create it...**, which would add a place to TMDb's list. On the first dry
run (2026-11-11) 16 places in 20 matched; the misses were names TMDb writes
differently ("Katsushika, Tokyo, Japan" for "Katsushika, Japan").

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

The scripts handle both:

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
  restarts the browser once, and ends the attempt if it happens again (v2: the
  run then waits and starts again, see below). Over the 1061
  records of the run before that incident, 1046 were written and the longest run
  without a write was 1, so the threshold sits far above normal.
- The client timeout is 60 s and the page load timeout 45 s, so a dead browser is
  noticed in one minute instead of two, and a merely slow page raises an ordinary
  `TimeoutException`.
- When every attempt fails, the v1 scripts stop, the stored cursor still pointing
  at the last record actually written, so running them again resumes there.

### The v2 scripts never stop on an error

Since 1.0.19 the v2 scripts run their work under `run_until_done`
([selenium_tmdb_common.py](selenium_tmdb_common.py)): any error that would have
ended the run (Chrome lost three times, 8 records in a row writing nothing, the
SFTP server unreachable, TMDB still answering 429 after `THROTTLE_WAITS`, any
bug) prints its traceback, logs a `run_error` event, waits, then starts the work
again: the export is downloaded again (a new day brings a new CSV), the browser is
replaced by a fresh, logged-in one, and the run resumes from the stored cursor.
The wikidata_id script does not redo the datasets it already finished.

- Waits: 1, 5, 15, then 30 minutes for every next error (`RETRY_WAITS`); after a
  429 that would not lift, always 30 minutes (`RETRY_WAIT_THROTTLED`). A run that
  had kept going 30 minutes before failing starts again from the 1-minute wait.
  The console prints the time of the next attempt.
- It is a wait, never a workaround: the run comes back to TMDB on the same
  account, from the same address, after the pause.
- Only two things end the program: Ctrl+C, and a wrong SFTP host key
  (`SFTP_SSHHOSTKEYFINGERPRINT` mismatch), a security failure that no wait repairs.
  The end of the CSV (or `--max-rows`) ends it normally.
- A run left alone therefore keeps retrying a lasting fault (a CAPTCHA, an expired
  TMDB password, a page TMDB changed) every 30 minutes: look at the `run_error`
  lines when a run seems to stand still.

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
then set the pause to **2 s** (2026-11-08). Measured on 2026-11-09 over 3,430
persons in two runs: a median **5.3 s** per person (5.0 to 5.5 s for 9 persons in
10 on the first run, up to 6.8 s towards the end of the second), so about 3.3 s
of TMDb work on top of the pause.

**Changing the pause during a run.** `PAUSE_BETWEEN_ROWS` is read from `.env`
(`PAUSE_BETWEEN_ROWS=2`, in seconds, decimals allowed), at the first person and
then every 15 minutes (`PAUSE_RELOAD_EVERY` = 900 s), so editing the line takes
effect within 15 minutes, without restarting the script. The console prints the
pause at start and every change it picks up. A missing key keeps the constant of
the script (2 s), an invalid value (text, negative) keeps the previous pause with
a warning. Only that key is read again: credentials and the other settings are
read once, at start.

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

1. Lower `PAUSE_BETWEEN_ROWS` (in `.env` since 2026-11-09): done, 5 s down to
   2 s on 2026-11-08 (1 s was tried the same morning). Philippe's call, not a default: the pause is there
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
scripts are:

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

The wikidata_id script writes one **JSON object per line** (JSON Lines) to a file
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
| `event` | `wikidata_id_write`, or the `dataset_start` / `dataset_end` pair that frames each dataset and carries the row count and the final counters, or `run_error` (v2: an error the run waits out, with `error_type`, `error`, `failure`, `wait_s`, `throttled`). |
| `action` | `set`, or `clear` when a QID is erased from a conflicting record before the fix. |
| `outcome` | `success`, `skipped` (TMDB refused the record) or `failed` (the write was attempted and did not stick). |
| `reason` | `page_load_timeout`, `page_not_found`, `translation_failed`, `field_not_found`, `locked`, `field_not_editable`, `field_write_refused`, `save_not_confirmed`, `session_lost`; for the primary facts also `already_set`, `place_not_found` (no place of that exact name in TMDb's list), `dry_run`. Null on success. |
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
  or chromedriver died under the loop. The script restarts the browser, logs
  back in and retries the record by itself, up to three times, as described in
  [When Chrome crashes](#when-chrome-crashes). If it gives up, the v2 scripts
  wait and start again by themselves; the v1 scripts stop, the `%store` cursor
  still pointing at the last record written, and running them again resumes there.
- **Chrome shows "Aw, Snap!" / "Aïe aïe aïe" with `Out of Memory`**: the renderer
  exhausted its memory. Nothing raises in that state, which is why the script
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
- **The script stops writing, Chrome sits on the last page, no error, no CPU, and
  the console title starts with `Sélection` / `Select`**: a click in the command
  prompt window started a Quick Edit selection, and Windows froze the script at its
  next print (2026-11-09, ten minutes on one record). Press Esc in the window and it
  resumes where it was. Since 1.0.18 the v2 scripts turn Quick Edit off for their
  window as they start (`disable_console_quick_edit` in `selenium_tmdb_common.py`);
  the `.bat` launchers cannot, `cmd.exe` puts the console mode back after every
  program it runs. The v1 scripts do not, use Esc there.
- **Records skipped in bulk, nothing written**: after 8 records in a row write
  nothing the run restarts Chrome, then ends the attempt if it happens again (v2:
  it waits and starts again, v1: it stops). Check in the browser whether TMDB is showing an
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
