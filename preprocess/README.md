# selenium-tmdb / preprocess

VPS-side, Dockerised job that produces the CSV input consumed by the Selenium
notebooks at the repository root. It queries the MariaDB / MySQL database that
backs the CitizenPhil application, exports the rows that need fixing on TMDB,
and writes one dated CSV per entity type (movies, series, persons) into
subfolders that are then served over SFTP.

For the overall workflow and the consumer notebooks, see the
[root README](../README.md).

---

## Role in the pipeline

```
+--------------------+    SQL     +-----------+    write    +---------------------------+
| selenium-tmdb.py   |  -------> | MariaDB DB |  -------->  | wikidata-id-*-fix/        |
| (inside container) |           |            |             |   *-YYYYMMDD.csv          |
+--------------------+           +-----------+              +-----------+---------------+
        ^                                                              |
        | docker run                                                   | SFTP (served from $FOLDER_PATH)
        |                                                              v
+--------------------+                                       +-------------------------+
| selenium-tmdb.sh   |                                       | Notebooks on workstation |
| host cron / manual |                                       |  (root of this repo)     |
+--------------------+                                       +-------------------------+
```

For each `*.sql` file found next to `selenium-tmdb.py`, the script:

1. Reads the SQL.
2. Executes it against MariaDB through PyMySQL.
3. Creates an output directory named after the SQL file stem
   (e.g. `wikidata-id-movie-fix/`).
4. Writes the result set as `<stem>-YYYYMMDD.csv` with `;` separator,
   `"`-quoted fields, and a literal `NULL` for null values.

It also updates a handful of `T_*SERVER_VARIABLE` rows so the rest of the
CitizenPhil stack can observe progress and runtime.

---

## Folder contents

| Path | Purpose |
| --- | --- |
| [Dockerfile](Dockerfile) | Builds the `selenium-tmdb-python-app` image from `python:3.10.5-slim-buster`. Contains no secrets — does not `COPY` `.env` and uses no secret-bearing `ENV` directives. |
| [.dockerignore](.dockerignore) | Excludes `.env`, generated CSV folders, VCS state and host launcher scripts from the build context so they cannot leak into image layers, build cache, or registries. |
| [selenium-tmdb.py](selenium-tmdb.py) | Entry point — runs every `*.sql` in this folder and writes one CSV per query. |
| [selenium-tmdb.sh](selenium-tmdb.sh) | Host launcher: builds the image if needed and runs the container detached with `--env-file` for secrets. |
| [citizenphil.py](citizenphil.py) | Shared helpers: DB connection, server-variable get/set, SQL escaping, error handling. |
| [wikidata-id-movie-fix.sql](../doc/sql/wikidata-id-movie-fix.sql) | Movies whose TMDB `ID_WIKIDATA` is missing/invalid while Wikidata has a match by IMDb ID. |
| [wikidata-id-serie-fix.sql](../doc/sql/wikidata-id-serie-fix.sql) | Same for TV series. |
| [wikidata-id-person-fix.sql](../doc/sql/wikidata-id-person-fix.sql) | Same for persons. |
| [wikidata-id-movie-fix/](wikidata-id-movie-fix/) | Generated CSVs for movies (git-ignored). |
| [wikidata-id-serie-fix/](wikidata-id-serie-fix/) | Generated CSVs for series (git-ignored). |
| [wikidata-id-person-fix/](wikidata-id-person-fix/) | Generated CSVs for persons (git-ignored). |
| [on.sh](on.sh) / [off.sh](off.sh) | Enable / disable the launcher by renaming `selenium-tmdb.sh`. Handy when chaining with cron. |
| [requirements.txt](requirements.txt) | Python deps: `pymysql`, `numpy`, `pytz`, `python-dotenv`. |
| [.env.example](.env.example) | Template for the container's `.env` (DB credentials + timezone). |

---

## SQL queries

The three `.sql` files share the same shape — they pick TMDB records whose
`ID_WIKIDATA` is `NULL`, empty, or does not match the canonical `^Q[0-9]+$`
regex, but for which a row exists in the corresponding `T_WC_WIKIDATA_*_V1`
table with a matching IMDb ID. They also surface any TMDB record that already
holds the target Wikidata ID, so the consumer notebook can clear the duplicate
before applying the fix.

Output columns (as joined / aliased by the queries):

- `ID_MOVIE` / `ID_SERIE` / `ID_PERSON` — TMDB ID to update.
- `ID_WIKIDATA` — target Wikidata ID to write.
- `ID_IMDB` — the IMDb ID that links the two records.
- `ID_WIKIDATA_*` — the Wikidata-side ID (informational).
- `ID_TMDB_WIKIDATA` — the current value stored on TMDB (informational).
- `TITLE` / `NAME` — display label.
- `ADULT` — adult-content flag.
- `ID_*_ERASE_WIKIDATA_ID` — TMDB ID of a conflicting record that must be
  cleared first; `NULL` when none.

---

## Configuration

### Secrets policy

Secrets are **never** baked into the image. Concretely:

- The [Dockerfile](Dockerfile) does not `COPY` any `.env` file and declares no
  secret-bearing `ENV` lines — only non-sensitive defaults belong in the
  image.
- [.dockerignore](.dockerignore) excludes `.env` (and `.env.*` except
  `.env.example`) from the build context, so the secrets file cannot leak
  into image layers, the build cache, or any registry the image is pushed to.
- At runtime the [selenium-tmdb.sh](selenium-tmdb.sh) launcher injects the
  variables with Docker's `--env-file` option, reading a host-managed file
  that lives **outside** the app source tree
  (`/home/debian/docker/selenium-tmdb/.env`).

### Host-managed env file

Create the env file on the VPS, outside any directory that gets copied into
the image:

```bash
sudo install -m 600 -o debian -g debian /dev/null /home/debian/docker/selenium-tmdb/.env
```

Populate it from [.env.example](.env.example):

```dotenv
DB_HOST=localhost
DB_PORT=3306
DB_USER=your_mysql_username
DB_PASSWORD=your_mysql_password
DB_NAME=your_database_name
DB_NAMESPACE=your_database_namespace   # SQL prefix, e.g. "cp_"
USER_TIMEZONE=Europe/Paris
```

`DB_NAMESPACE` is prepended to the `SERVER_VARIABLE` table name when
`citizenphil.py` reads/writes runtime counters, so it must match the prefix
used by the rest of the CitizenPhil schema.

`.env` is both git-ignored and docker-ignored. Do **not** commit it and do
**not** bake it into an image.

---

## Running on the VPS

### One-shot via the launcher

`selenium-tmdb.sh` is the canonical entry point on the VPS. It refuses to
start if the host-managed env file is missing, otherwise builds the image and
launches the container detached with the working directory mounted into
`/app` and the secrets injected via `--env-file`:

```bash
cd /home/debian/docker/selenium-tmdb
./selenium-tmdb.sh
```

What it does:

```bash
docker build -t selenium-tmdb-python-app .
docker run -d --rm --network="host" \
    --env-file /home/debian/docker/selenium-tmdb/.env \
    -v $(pwd):/app \
    --name selenium-tmdb \
    selenium-tmdb-python-app
```

- `--env-file /home/debian/docker/selenium-tmdb/.env` injects the secrets at
  **runtime** from a host-managed file that lives outside the app source
  tree. The file is excluded from the build context by `.dockerignore`, so it
  never ends up in image layers, build cache, or any pushed registry image.
- `--network="host"` lets the container reach the local MariaDB instance via
  `DB_HOST=localhost` / `127.0.0.1`. Adjust if your DB lives elsewhere.
- `-v $(pwd):/app` bind-mounts the folder, so the generated CSVs land directly
  on the host filesystem where the SFTP server can serve them.
- `--rm` removes the container as soon as the script exits.

Tail logs while it runs:

```bash
docker logs -f selenium-tmdb
```

### Pause / resume the cron

`on.sh` and `off.sh` simply rename `selenium-tmdb.sh` to
`selenium-tmdb-off.sh` (and back), which is convenient when the script is
invoked from cron and you need to disable it temporarily without editing the
crontab.

### Manual run without Docker

For development on the VPS itself:

```bash
pip install -r requirements.txt
python ./selenium-tmdb.py
```

You still need a populated `.env` (in this folder, since `citizenphil.py`
loads it via `Path(__file__).resolve().with_name(".env")` for the non-Docker
path) and a reachable MariaDB.

### Manual `docker run`

If you need to launch the container without `selenium-tmdb.sh`, mirror the
flags it uses — in particular, **always** pass secrets via `--env-file` and
never via inline `-e KEY=value` (which would expose them in shell history and
`docker inspect` output):

```bash
docker build -t selenium-tmdb-python-app .
docker run -d --rm --network=host \
    --env-file /home/debian/docker/selenium-tmdb/.env \
    -v $(pwd):/app \
    --name selenium-tmdb \
    selenium-tmdb-python-app
```

---

## Output

Each run produces, for every `*.sql` file in this folder:

```
<sql-stem>/<sql-stem>-YYYYMMDD.csv
```

Example after a single run on 2026-05-19:

```
wikidata-id-movie-fix/wikidata-id-movie-fix-20260519.csv
wikidata-id-serie-fix/wikidata-id-serie-fix-20260519.csv
wikidata-id-person-fix/wikidata-id-person-fix-20260519.csv
```

CSV format:

- Separator: `;`
- Quote character: `"` (doubled inside values)
- Header row built from the cursor description
- `NULL` literal for SQL nulls

Re-running the same day overwrites the day's CSV; previous days are kept until
deleted manually.

---

## Server variables

`citizenphil.py` exposes `f_getservervariable` / `f_setservervariable`, which
read and write `<DB_NAMESPACE>SERVER_VARIABLE` rows. `selenium-tmdb.py`
updates the following keys on each run:

| Variable | Meaning |
| --- | --- |
| `strseleniumtmdbstartdatetime` | Start timestamp of the run (Paris time). |
| `strseleniumtmdbenddatetime` | End timestamp of the run. |
| `strseleniumtmdbcurrentprocess` | Currently executing step (cleared at end). |
| `strseleniumtmdbprocessesexecuted` | Comma-separated list of executed steps for the current run. |
| `strseleniumtmdbprocessesexecutedprevious` | Same, for the previous run. |
| `strseleniumtmdbtotalruntime` | Human-readable duration; set to `RUNNING` while live. |
| `strseleniumtmdbtotalruntimesecond` | Duration in seconds. |
| `strseleniumtmdbtotalruntimeprevious` | Previous run's duration. |
| `strseleniumtmdbprocess1SQLqueriescount` | Number of `.sql` files processed in the current run. |
| `strseleniumtmdbdatetime` | Timestamp of the last processed file. |

MySQL lock-wait-timeout errors (code 1205) are caught, logged, and retried up
to three times by `f_sqlupdatearray`.

---

## Adding a new query

1. Drop a new `<name>.sql` next to `selenium-tmdb.py`. The script picks every
   `*.sql` in the folder in alphabetical order.
2. Make sure the query returns column names that downstream consumers expect
   (the notebooks at the repo root key on `ID_MOVIE` / `ID_SERIE` /
   `ID_PERSON`, `ID_WIKIDATA`, `ID_*_ERASE_WIKIDATA_ID`).
3. Rebuild the image (the `Dockerfile` `COPY . /app/` step embeds the SQL
   files into the image) — or just rely on the bind mount and re-run
   `selenium-tmdb.sh`.

---

## License

Released under the [MIT License](LICENSE). © 2025 Philippe Vaugouin.
