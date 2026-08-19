# AGENTS.md - Agent Guide for selenium-tmdb

This file gives you the agentic context you need to work on this codebase safely. For project overview, features, install / deploy steps and human-facing security / performance / troubleshooting material, read @README.md — that file is canonical and not duplicated here.

This is the single canonical guide for autonomous coding agents in this repository. Assistant-specific files such as @CLAUDE.md, and any future tool-specific guide such as `GEMINI.md`, should only point here and should not duplicate repository instructions.

- For any project update, keep documentation aligned:
  - Update `README.md` for user-facing behavior, configuration, setup, deployment, troubleshooting, or verification changes.
  - Update this file only when agent workflow or safety context changes.

---

## Related repositories (project ecosystem)

`selenium-tmdb` is the acquisition-side automation repo of the **Agent BBB** movie/TV database system (owner `vaugouin`). It drives the **themoviedb.org website** through a real, logged-in Chrome session to **write Wikidata QIDs into TMDb external-ID fields** for movies, TV series, and persons — data that the official TMDb API does not let you write. It therefore complements the read-side Wikidata crawlers (`sparql-movies-persons` / `sparql-crawler` / `wikidata-crawler`), which pull Wikidata facts into the shared MySQL/MariaDB database (`T_WC_*` tables); this repo closes the loop by pushing the resulting QIDs back onto TMDb. The repair list it consumes is computed off-site by the VPS-side `preprocess/` job from that same database.

The canonical sibling-repo roster lives in `tmdb-front/doc/related-repositories/related-repositories.txt`.

## Where things live (file → role)

| Path | Role |
| --- | --- |
| [selenium-tmdb-wikidata_id.ipynb](selenium-tmdb-wikidata_id.ipynb) | Unified, recommended notebook. Cell sequence: imports → `.env` credential check → `DATASETS` config → pure-function helpers → SFTP download + Chrome login → `process_dataset` for movies/series/persons → return to TMDb home. Resumable via `%store`. |
| [selenium-tmdb-wikidata_id-movies01.ipynb](selenium-tmdb-wikidata_id-movies01.ipynb) | Legacy standalone notebook for movies only. |
| [selenium-tmdb-wikidata_id-series01.ipynb](selenium-tmdb-wikidata_id-series01.ipynb) | Legacy standalone notebook for TV series only. |
| [selenium-tmdb-wikidata_id-persons01.ipynb](selenium-tmdb-wikidata_id-persons01.ipynb) | Legacy standalone notebook for persons only. |
| [preprocess/](preprocess/) | Dockerised VPS-side job that runs the `*.sql` queries against MariaDB and emits one date-stamped CSV per entity type. Has its own [README](preprocess/README.md); not run locally. |
| [preprocess/wikidata-id-{movie,serie,person}-fix.sql](preprocess/) | The join logic that selects TMDb records needing a `wikidata_id` fix. |
| [data/](data/) | SFTP-mirrored CSVs (under `wikidata-id-{movie,serie,person}-fix/`) and `selenium-tmdb-wikidata_id.log`. Git-ignored. |
| [requirements.txt](requirements.txt) | `pandas`, `python-dotenv`, `selenium`, `webdriver-manager`, `paramiko`. |
| [.env.example](.env.example) | Template for the local `.env`. |

The notebooks are the only locally-run code. There are no `.py` modules at the repo root — all helper functions (`download_new_csv_files`, `get_latest_csv`, `init_driver`, `login_tmdb`, `set_wikidata_id`, `clear_wikidata_id`, `process_dataset`) live in notebook cells. Per-entity differences are data-driven through the `DATASETS` list (remote folder, ID column, `entity_path` for the `movie|tv|person` URL fragment, `%store` cursor key).

## Code conventions

- Behavior is configured by the `DATASETS` config block, not by per-entity branching — when adding or changing an entity type, extend that list rather than duplicating logic.
- Resumable cursors use the IPython `%store` magic (`lngmovieidstart`, `lngserieidstart`, `lngpersonidstart`) so a run resumes after a crash/interrupt. The legacy single-entity notebooks share the same store keys as the unified notebook.
- DOM interaction uses Selenium **explicit waits** (`WebDriverWait` + `expected_conditions`); preserve that pattern instead of `time.sleep`-style polling when editing automation cells.
- Some log/error strings are in French (e.g. `Colonne ID_MOVIE manquante dans le fichier CSV`); this is expected, not a bug.

## Configuration & secrets

- Local config comes from a `.env` at the repo root, loaded via `python-dotenv`. Required keys (see [.env.example](.env.example)): `TMDB_LOGIN`, `TMDB_PASSWORD`, `SFTP_HOST`, `SFTP_LOGIN`, `SFTP_FOLDER`. The notebook raises `ValueError` if any are missing. Optional keys: `SFTP_PORT` (default `22`), `SFTP_SSHHOSTKEYFINGERPRINT`, `SFTP_KEY`, `SFTP_KEY_PASSPHRASE`, `SFTP_PASSWORD`.
- **SFTP authentication order** (`open_sftp_connection` in the helpers cell): SSH public key first — `SFTP_KEY`, else the `IdentityFile` for `SFTP_HOST` in `~/.ssh/config` (`IdentitiesOnly` honoured), else the default `~/.ssh/id_*` files, else an SSH agent — then `SFTP_PASSWORD` as fallback when set. Keep that order; the password path exists only as a second choice. A passphrase-protected key uses `SFTP_KEY_PASSPHRASE` or an interactive `getpass` prompt, never a plaintext value in the notebook.
- **Host verification** is pinned to `SFTP_SSHHOSTKEYFINGERPRINT` (WinSCP `SshHostKeyFingerprint` format, shared with the PowerShell scripts) via `FingerprintHostKeyPolicy`, not to `known_hosts`. A mismatch raises `HostKeyVerificationError` and must never be retried with the password fallback or downgraded to `AutoAddPolicy` — the `known_hosts` + `AutoAddPolicy` branch is only for an empty fingerprint, and it warns.
- `SFTP_FOLDER` must point at the VPS directory containing the `wikidata-id-{movie,serie,person}-fix/` subfolders produced by the `preprocess/` job.
- **CSV input format**: `;`-separated, `"`-quoted, one row per record to fix. Header columns: `ID_MOVIE`/`ID_SERIE`/`ID_PERSON` (TMDb numeric ID to update), `ID_WIKIDATA` (target QID, e.g. `Q644554`), `ID_IMDB` (match key, informational), `TITLE`/`NAME` and `ADULT` (informational), and `ID_*_ERASE_WIKIDATA_ID` (TMDb ID of a conflicting record whose QID must be cleared first; may be empty / `NULL` / `NaN`). The notebook picks the most recently modified CSV per dataset.
- **Selenium / ChromeDriver**: a **headed** Chrome session is used (login may trigger a manual CAPTCHA). The matching ChromeDriver is fetched automatically by `webdriver-manager` (cached in `~/.wdm/`); delete that dir to force a re-download after a Chrome upgrade.
- **Never commit credentials.** `.env` and `data/` are git-ignored. NOTE: the working tree's root `.env` currently contains real TMDb and SFTP credentials in plaintext — it is correctly git-ignored, but do not echo its contents into commits, logs, or notebook output, and do not relocate it into a tracked path.
- **Deployment / Docker**: the root notebooks are **run locally in Jupyter, not containerized** (no `Dockerfile` at the repo root). The **only** dockerized part is the `preprocess/` subjob: its `preprocess/Dockerfile` (Python 3.10 slim, `CMD ["python", "./selenium-tmdb.py"]`) builds the VPS-side image that runs the `*.sql` queries against MariaDB and emits the date-stamped fix CSVs. Do not assume the notebooks themselves run in a container.

## Safety

- This repo **automates a logged-in human session on a third-party website (themoviedb.org) and MODIFIES live external records** — it writes (and, in conflict cases, clears) Wikidata IDs on real movie/TV/person entries. Treat every run as a production write to someone else's system.
- Run it **deliberately and interactively** from Jupyter while watching the browser; never wire it into an unattended CI/cron loop. It must respect TMDb's Terms of Service and any rate limits — the resumable `%store` cursor exists so an interrupted run can be paused and resumed rather than hammered.
- The `clear_wikidata_id` path is destructive (it erases a QID from a conflicting TMDb record before applying the fix). Verify the `ID_*_ERASE_WIKIDATA_ID` source rows before running against fresh CSV data.
- Records whose `wikidata_id` field is moderator-**locked** are intentionally skipped — do not add code to force-edit locked fields.
- The committed historical `data/T_WC_TMDB_*_UPDATE_*-fix.csv` files predate the current `data/` ignore rule and use an older schema; do not treat them as the live input. The active inputs are the SFTP-mirrored `data/wikidata-id-*-fix/` folders.

---

**Last Updated**: 2026-08-10
**Current Version**: 1.0.0

## Backlog (Nestor second-brain)

The prioritized, agent-ready implementation backlog for this repo lives in the **Nestor**
knowledge repo (a separate repo, not cloned alongside this one):

- This repo: `C:\Users\vaugo\Nestor\projets\t2s-backlog\repos\selenium-tmdb.md`
- Cross-repo dashboard: `C:\Users\vaugo\Nestor\projets\t2s-backlog\index.md`

Consult it before implementing: tasks are `SELENIUM-TMDB-NNN` with status (done / in-progress /
todo), priority, and quick-wins. NOTE: these are local paths on Philippe's PC and do not
resolve on the VPS or on cloud agents (claude.ai/code).

## SQL files live in `doc/sql/`

Stack-wide convention, set 2026-08-20. Every **read-only** `.sql` of this repo, audit
queries, monitoring queries, exports, reference DDL dumps, lives in `doc/sql/`, never
at the root and never in a `doc/queries/` of its own.

**This repo currently has no `doc/sql/`, and that is correct.** Its only three `.sql`
files, `wikidata-id-movie-fix.sql`, `wikidata-id-serie-fix.sql` and
`wikidata-id-person-fix.sql`, are **executed** by process 1 of `preprocess/selenium-tmdb.py`,
so they fall under the first exception below and stay in `preprocess/`.

The trap is worth spelling out, because it cost a broken run on 2026-08-20. That process
does not name the files: it does `sorted(Path(__file__).resolve().parent.glob("*.sql"))`
(`preprocess/selenium-tmdb.py:56-57`), executes whatever it finds **next to itself**, and
writes each result to `preprocess/<basename>/<basename>-YYYYMMDD.csv` for the SFTP upload
the notebooks consume. A wildcard leaves no reference to grep for, so moving the files
away broke nothing visibly: the glob simply matched zero files and the process produced
no CSV at all. Two consequences. Never move a `.sql` out of `preprocess/`. And never add
a `.sql` to `preprocess/` that you do not want executed on the next run.

Two deliberate exceptions, and they are the reason the rule is worded around reading
rather than around file type. A `.sql` **executed by code** stays where the code expects
it, because moving it breaks a run silently. And a `.sql` that **writes** (migration,
seed, `DELETE` cleanup) stays put too: it belongs to a procedure, not to documentation.
When in doubt, ask whether running the file twice by accident would change the database.
If yes, it is not a `doc/sql/` file.
