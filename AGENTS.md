# AGENTS.md - Agent Guide for selenium-tmdb

Rules an agent needs to work on this codebase safely. Overview, layout, setup, configuration, CSV schema, log format and troubleshooting live in @README.md (and [preprocess/README.md](preprocess/README.md) for the VPS job), which are canonical: update them for any user-facing change, and update this file only when agent workflow or safety context changes. `CLAUDE.md` and any other tool-specific file only point here.

---

## Related repositories (project ecosystem)

Part of **Agent BBB** (owner `vaugouin`; sibling roster in `%USERPROFILE%/Nestor/projets/t2s-backlog/topics/related-repositories.txt`). This repo drives the **themoviedb.org website** through a logged-in Chrome session to **write Wikidata QIDs into TMDb external-ID fields**, which the TMDb API cannot write. It closes the loop opened by the Wikidata crawlers (`wikidata-crawler`, `sparql-crawler`) that fill the shared MariaDB; `tmdb-crawler` processes 23/29/30 then read the QIDs back from TMDb.

## Where things live (file → role)

See README § Repository layout. Non-obvious points: the notebooks are the only locally-run code, and all helpers (`process_dataset`, `set_wikidata_id`, `clear_wikidata_id`, ...) live in notebook cells, not in `.py` modules. The `-movies01` / `-series01` / `-persons01` notebooks are legacy; the unified `selenium-tmdb-wikidata_id.ipynb` is the one to edit. Only `preprocess/` is dockerised (VPS side); never assume the notebooks run in a container.

## Code conventions

- Per-entity differences are data-driven through the `DATASETS` list (six entries: fix and replace per entity, each with its own `store_key`). Extend it rather than branching per entity.
- Resumable cursors use `%store` (`lngmovieidstart`, ..., `lngmoviereplaceidstart`, ...); the legacy notebooks share the fill keys. Writing the cursor is half the pair: `get_store_value` must read it back, or every relaunch restarts at the top of the CSV.
- DOM interaction uses explicit waits (`WebDriverWait` + `expected_conditions`), never `time.sleep` polling.
- The browser is disposable: `process_dataset` **returns** the driver it ends with (crashes are recovered by `restart_browser`). Callers must rebind: `driver = process_dataset(driver, dataset)`.
- Only `is_browser_gone` decides a failure means a dead browser, and only `BrowserSessionLost` marks a lost TMDB session. Keep both narrow: catching `WebDriverException` broadly would restart Chrome over a missing element, and a record skipped for a real reason (locked, 404) must keep advancing the cursor.
- Navigate through `open_page` / `open_edit_page`, never a bare `driver.get`: they skip a page that never loads and recognise Chrome's own error page. Never treat "no exception" as "the page loaded" (an out-of-memory "Aw, Snap!" raises nothing); check `get_chrome_error_code`.
- No CDP call between navigations without a full run behind it: `Memory.forciblyPurgeJavaScriptMemory` hung every navigation from Chrome 154 and lost over a hundred records (README § Troubleshooting). Tell-tale: only the first row after each Chrome start succeeds.
- Click Save through `click_save_button`, never a bare `.click()`: the OneTrust cookie banner covers it. `login_tmdb` declines the banner once per browser.
- Match TMDB buttons on their **text**, not icon classes (they differ between pages, and a miss reads silently as "already exists").
- Every write attempt is traced by `log_wikidata_write` (format: README § Logs). Each early `return False` of `set_wikidata_id` / `clear_wikidata_id` carries its own `trace(outcome, reason)`; a new exit path needs one, and a new reason must join the closed vocabulary rather than be invented in place. `append_log_event` swallows its errors on purpose. Log values go through `log_value` / `log_int` (pandas `numpy.int64` and `NaN` are not JSON).
- Any new skip path must be genuinely rare: `MAX_CONSECUTIVE_SKIPS` stops the run.
- Some log/error strings are in French; that is expected.

## Configuration & secrets

Keys and auth: README § Configuration and `.env.example`. Rules:

- Keep the SFTP auth order (key first, password only as fallback). A passphrase comes from `SFTP_KEY_PASSPHRASE` or a `getpass` prompt, never plaintext in the notebook.
- Host verification is pinned to `SFTP_SSHHOSTKEYFINGERPRINT`. A mismatch (`HostKeyVerificationError`) must never be retried with the password nor downgraded to `AutoAddPolicy`; the `known_hosts` branch exists only for an empty fingerprint.
- A new export needs no wiring: `preprocess/<name>.sql` produces `preprocess/<name>/<name>-YYYYMMDD.csv`.
- The working tree's root `.env` holds real TMDb and SFTP credentials (git-ignored): never echo it into commits, logs or notebook output, nor move it to a tracked path.

## Safety

- Every run **modifies live records on a third-party site** (writes, and in conflict cases clears, QIDs on TMDb). Run it deliberately and interactively from Jupyter while watching the browser; never wire it into CI/cron. Respect TMDb's ToS and rate limits.
- `clear_wikidata_id` is destructive: verify the `ID_*_ERASE_WIKIDATA_ID` rows of a fresh CSV before running.
- The `*_replace` datasets overwrite valid data: read the CSV and watch the first run of each.
- Moderator-**locked** fields are skipped on purpose; never add code to force them.
- Crash recovery (bounded by `BROWSER_RESTART_ATTEMPTS`) does not make the run unattended: a CAPTCHA needs a human, and each restart replays the current record live.
- A record without an English translation redirects to `/translate/...`; `create_english_translation` then makes a real write to TMDB.

---

**Last Updated**: 2026-10-31
**Current Version**: 1.0.7

## Backlog (Nestor second-brain)

Tasks `SELENIUM-TMDB-NNN` (status, priority, quick wins) live in the Nestor repo; consult before implementing: `C:\Users\vaugo\Nestor\projets\t2s-backlog\repos\selenium-tmdb.md` (dashboard: `...\t2s-backlog\index.md`). These paths exist only on Philippe's PC, not on the VPS or cloud agents.

## The shared database is entirely `utf8mb4_unicode_ci`, so do not cast to CHAR

Every table of `vaugouindb` is `utf8mb4_unicode_ci`, so column against column is safe. A value **produced by a function** (`CAST(x AS CHAR)`, `CONVERT`, `CONCAT` over a number) inherits the connection collation (`utf8mb4_general_ci`), and comparing it to a column raises `ERROR 1267 Illegal mix of collations`; literals never do. So write `corrob.VALUE_EXTERNAL_ID = M1.ID_MOVIE` bare and let MariaDB compare numerically. When a `COLLATE` is really needed, put it on the non-indexed side.

## Filling and replacing are two jobs, and they do not share a file

`-fix.sql` fills a `wikidata_id` that is empty or malformed; `-replace.sql` overwrites a valid but wrong QID. Never merge them back. The robot does not read what it erases (`field.clear()` then type), so the whole decision is made in the query.

- **Guard 3** (replace): the candidate QID must itself name *that* TMDb record in `P4947`/`P4983`/`P4985`; an IMDb match alone is enough to fill, not to contradict.
- **Guard 4** (fill, 2026-10-10): a fill row that would clear another record (`ID_*_ERASE_WIKIDATA_ID`) is exported only when the QID names this record **and does not also name the holder**; otherwise the QID stays put. Without it, TMDb duplicates traded the QID on every run.

Measurements and reasoning are in the header comments of the `preprocess/*.sql` files. When hunting such loops in the logs, group changed writes by `tmdb_id` and look for alternating `set` / `clear` across days. TMDb seems to silently refuse a QID another record holds, while the notebook still logs `success` (it checks the input box, not the saved value).

## SQL files live at the root, and never in `preprocess/` unless they are meant to run

Philippe's decision (2026-09-02), overriding the stack-wide `doc/sql/` convention for this repo: there is no `doc/sql/` here; do not create one. A non-executed `.sql` (recipe, test) goes at the root, or in `archive/` once used.

**The rule that does not bend is about `preprocess/`.** `preprocess/selenium-tmdb.py` runs `sorted(Path(__file__).resolve().parent.glob("*.sql"))`: every `.sql` next to it is executed each morning, each through a single `cursor.execute()`, and written to `preprocess/<stem>/<stem>-YYYYMMDD.csv` for the notebooks. A wildcard leaves no reference to grep for, so:

- never move a `.sql` out of `preprocess/` (2026-08-20: the glob matched nothing, no CSV, no error);
- never add a `.sql` there that is not meant to run, nor one chaining several statements (2026-09-02: error 1064 took the real exports down with it).
