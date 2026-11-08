#!/usr/bin/env python
"""Primary facts into TMDb (persons_primary_facts), v2.

Copy of selenium-tmdb-deathday.py: the shared code lives in
selenium_tmdb_common.py, and Chrome is a real one on a persistent profile that
keeps the TMDB session (log in once by hand, see README). Every real run
MODIFIES LIVE RECORDS on themoviedb.org: run it deliberately, in a terminal,
while watching the browser (never from CI or cron).

    python selenium-tmdb-deathday-v2.py --dry-run --max-rows 20   # cells 5, 7, 8 with DRY_RUN = True
    python selenium-tmdb-deathday-v2.py                           # cell 7 as it stands: DRY_RUN = False,
                                                                  # MAX_ROWS = 0, FILL_FIELDS = deathday birthday gender
    python selenium-tmdb-deathday-v2.py --diagnostic 1265047      # cells 5 and 6, read-only
    python selenium-tmdb-deathday-v2.py --reset-cursor            # cell 9
    python selenium-tmdb-deathday-v2.py --debug-login             # cells 10 and 11
"""

import argparse
import os
import sys
from pathlib import Path

# The relative paths (.env, data/, logs/) are the repository's wherever the
# script is started from; the library resolves them on import.
os.chdir(Path(__file__).resolve().parent)

import selenium_tmdb_common
from selenium_tmdb_common import *

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

# The log helpers live in the library and read its own LOG_BASENAME.
selenium_tmdb_common.LOG_BASENAME = LOG_BASENAME

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

    parser = argparse.ArgumentParser(description='Primary facts into TMDb, in a real Chrome (v2).')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--diagnostic', nargs='?', type=int, const=1265047, metavar='PERSON_ID',
                        help='cell 6, read-only: the primary facts fields of one person (default: 1265047)')
    action.add_argument('--reset-cursor', action='store_true',
                        help='cell 9: the next real run starts at the top of the latest export')
    action.add_argument('--debug-login', action='store_true',
                        help='cells 10 and 11: inspect the login page, then log in and report')
    parser.add_argument('--dry-run', action='store_true',
                        help='cell 7 with DRY_RUN = True: pages checked, nothing saved')
    parser.add_argument('--max-rows', type=int, default=0, help='cell 7 MAX_ROWS: records per run, 0 for no limit (default: 0)')
    parser.add_argument('--fields', nargs='+', default=['deathday', 'birthday', 'gender'], metavar='FIELD',
                        help='cell 7 FILL_FIELDS (default: deathday birthday gender)')
    args = parser.parse_args()

    if args.reset_cursor:
        # Cell 9
        # Reset the cursor: the next real run starts at the top of the latest export.
        set_store_value(PRIMARY_FACTS_DATASET['store_key'], {})
        return

    driver = None
    try:
        if args.debug_login:
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
