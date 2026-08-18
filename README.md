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
   logs into TMDB.
5. **Cell 5** — runs `process_dataset` for movies, series, then persons.
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
  Chrome session. Solve it manually in the open window; the notebook keeps
  running once the form is submitted.
- **"Element 'Locked' exists on the page."** — the `wikidata_id` field is
  locked by a TMDB moderator. The script intentionally skips it; no action
  needed.
- **Chrome / ChromeDriver mismatch** — `webdriver-manager` installs the right
  driver on the first run; delete `~/.wdm/` to force a re-download if Chrome
  has been upgraded.

---

## License

Released under the [MIT License](LICENSE). © 2025 Philippe Vaugouin.
