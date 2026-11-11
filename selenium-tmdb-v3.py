"""selenium-tmdb v3: one script for everything the robot writes on TMDb.

- external_ids tab of movies, series and persons, in ONE visit and one Save per record:
  wikidata_id (exports wikidata-id-<entity>-fix, and -replace with --replace), and the
  ids of external-ids-<entity>-fix (IMDb, TheTVDB, Facebook, Instagram, X, TikTok,
  YouTube);
- primary_facts tab of persons (Day of Death, Birthday, Gender, Place of Birth), from
  primary-facts-person-fix, through the engine of selenium-tmdb-deathday-v2.py.

One resume rule for everything: a run starts at the top of each export; what a previous
real run wrote, or found locked or already set, is read back from the logs and skipped
without opening the page. The stored cursor only resumes an interrupted run on the same
CSV files and fields. An error never ends the run (run_until_done): it waits, then
starts again from the cursor.

The code of the two v2 scripts is loaded as modules (wd, pf), not copied: a fix there is
a fix here. This file adds the external_ids visit and the orchestration.
Logs: logs/selenium-tmdb-YYYYMMDD.log, same JSON Lines format (README, Logs).
"""

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

# The scripts keep data/ and logs/ next to them, whatever the launch folder.
os.chdir(Path(__file__).resolve().parent)

import selenium_tmdb_common
from selenium_tmdb_common import *


def load_script(file_name, module_name):
    """Load a v2 script as a module (its main() is behind __name__ == '__main__')."""
    spec = importlib.util.spec_from_file_location(module_name, Path(__file__).resolve().parent / file_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wd = load_script('selenium-tmdb-wikidata_id-v2.py', 'wikidata_id_v2')
pf = load_script('selenium-tmdb-deathday-v2.py', 'primary_facts_v2')

# Both imports set the library's LOG_BASENAME to their own; v3 writes its own file, and
# 'selenium-tmdb-*.log' (pf.already_handled_fields, already_handled_external) matches
# every file, v1 and v2 included: the history of all the robots counts.
LOG_BASENAME = 'selenium-tmdb'
selenium_tmdb_common.LOG_BASENAME = LOG_BASENAME
pf.LOG_BASENAME = LOG_BASENAME

# =============================================================================
# Settings
# =============================================================================
DRY_RUN = False
MAX_ROWS = 0                      # records per phase and entity; 0 for no limit

# external_ids fields, in page order. youtube_id is left out by default: Wikidata P2397
# is a channel id ("UC..."), and what TMDb expects there is not verified yet.
EXTERNAL_FIELDS = ['wikidata_id', 'imdb_id', 'tvdb_id', 'facebook_id', 'instagram_id',
                   'twitter_id', 'tiktok_id', 'youtube_id']
DEFAULT_FIELDS = [key for key in EXTERNAL_FIELDS if key != 'youtube_id'] + list(pf.PRIMARY_FIELDS)
FILL_FIELDS = list(DEFAULT_FIELDS)

# CSV column of external-ids-<entity>-fix -> field of the external_ids tab.
EXTERNAL_COLUMNS = {
    'ID_IMDB': 'imdb_id', 'ID_TVDB': 'tvdb_id', 'FACEBOOK_ID': 'facebook_id',
    'INSTAGRAM_ID': 'instagram_id', 'TWITTER_ID': 'twitter_id', 'TIKTOK_ID': 'tiktok_id',
    'YOUTUBE_ID': 'youtube_id',
}

ENTITIES = {
    'movie': {'entity_path': 'movie', 'id_column': 'ID_MOVIE', 'label_column': 'TITLE',
              'fix': 'wikidata-id-movie-fix', 'replace': 'wikidata-id-movie-replace',
              'external': 'external-ids-movie-fix', 'store_key': 'v3cursor_movie'},
    'tv': {'entity_path': 'tv', 'id_column': 'ID_SERIE', 'label_column': 'TITLE',
           'fix': 'wikidata-id-serie-fix', 'replace': 'wikidata-id-serie-replace',
           'external': 'external-ids-serie-fix', 'store_key': 'v3cursor_tv'},
    'person': {'entity_path': 'person', 'id_column': 'ID_PERSON', 'label_column': 'NAME',
               'fix': 'wikidata-id-person-fix', 'replace': 'wikidata-id-person-replace',
               'external': 'external-ids-person-fix', 'store_key': 'v3cursor_person'},
}
PHASES = ['movie', 'tv', 'person', 'primary_facts']
REPLACE = False


# =============================================================================
# Exports
# =============================================================================
def download_exports(phases, replace):
    """Mirror the exports this run reads. A folder the VPS has not produced yet is skipped."""
    folders = []
    for phase in phases:
        if phase == 'primary_facts':
            folders.append(pf.PRIMARY_FACTS_DATASET['remote_folder'])
            continue
        spec = ENTITIES[phase]
        folders += [spec['fix'], spec['external']] + ([spec['replace']] if replace else [])
    for folder in folders:
        try:
            download_new_csv_files(folder, folder)
        except FileNotFoundError:
            print(f'{folder}: no such folder on the VPS yet, skipped.')


def latest_csv_or_none(folder):
    try:
        return get_latest_csv(folder, folder)
    except FileNotFoundError:
        print(f'{folder}: no CSV, skipped.')
        return None


def clean(raw):
    """A CSV cell as text, None when empty. The exports write SQL NULL as the text NULL."""
    text = '' if raw is None else str(raw).strip()
    if not text or text.upper() in ('NULL', 'NAN', 'NONE'):
        return None
    return text.split('.')[0] if text.replace('.', '', 1).isdigit() else text


def build_worklist(spec, fields, replace):
    """Merge the exports of one entity into one list of records, each with its targets.

    Order: the wikidata_id rows first (short exports, no popularity), then the external
    ids rows, most popular first. A record found in both is visited once, at its first
    place, with every target.
    """
    records, files = {}, []

    def add(tmdb_id, source):
        if tmdb_id not in records:
            records[tmdb_id] = {'tmdb_id': tmdb_id, 'targets': {}, 'sources': [], 'label': None,
                                'erase': None, 'mode': None, 'csv_file': None, 'csv_row': None}
        record = records[tmdb_id]
        record['sources'].append(source)
        return record

    wikidata_sources = [('fix', spec['fix'])] + ([('replace', spec['replace'])] if replace else [])
    if 'wikidata_id' in fields:
        for mode, folder in wikidata_sources:
            csv_path = latest_csv_or_none(folder)
            if csv_path is None:
                continue
            files.append(csv_path.name)
            data = pd.read_csv(str(csv_path), sep=';', quotechar='"', dtype=str, keep_default_na=False)
            erase_column = spec['id_column'] + '_ERASE_WIKIDATA_ID'
            for index, row in data.iterrows():
                tmdb_id = log_int(clean(row.get(spec['id_column'])))
                qid = clean(row.get('ID_WIKIDATA'))
                if tmdb_id is None or qid is None or 'wikidata_id' in records.get(tmdb_id, {}).get('targets', {}):
                    continue
                record = add(tmdb_id, folder)
                record['targets']['wikidata_id'] = qid
                record['mode'] = mode
                record['erase'] = log_int(clean(row.get(erase_column)))
                record['label'] = clean(row.get(spec['label_column']))
                record['csv_file'], record['csv_row'] = csv_path.name, int(index)

    external_fields = [key for key in fields if key in EXTERNAL_COLUMNS.values()]
    if external_fields:
        csv_path = latest_csv_or_none(spec['external'])
        if csv_path is not None:
            files.append(csv_path.name)
            data = pd.read_csv(str(csv_path), sep=';', quotechar='"', dtype=str, keep_default_na=False)
            for index, row in data.iterrows():
                tmdb_id = log_int(clean(row.get(spec['id_column'])))
                if tmdb_id is None:
                    continue
                targets = {}
                for column, key in EXTERNAL_COLUMNS.items():
                    if key in external_fields and column in data.columns:
                        value = clean(row.get(column))
                        if value is not None:
                            targets[key] = value
                if not targets:
                    continue
                record = add(tmdb_id, spec['external'])
                record['targets'].update(targets)
                record['label'] = record['label'] or clean(row.get(spec['label_column']))
                record['wikidata_qid'] = clean(row.get('ID_WIKIDATA'))
                if record['csv_file'] is None:
                    record['csv_file'], record['csv_row'] = csv_path.name, int(index)
    return list(records.values()), files


# =============================================================================
# What previous runs already did (every log of every robot)
# =============================================================================
def already_handled_external():
    """(entity_path, tmdb_id, field[, value]) a previous real run wrote, or found locked or set.

    wikidata_id is keyed with its value: a new QID for the same record is a new target.
    Locked is keyed without value (None): whatever the QID, the field stays locked.
    """
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
                entity, tmdb_id = record.get('entity'), record.get('tmdb_id')
                if event == 'wikidata_id_write' and record.get('action') == 'set':
                    if record.get('outcome') == 'success':
                        handled.add((entity, tmdb_id, 'wikidata_id', record.get('wikidata_id')))
                    elif record.get('reason') == 'locked':
                        handled.add((entity, tmdb_id, 'wikidata_id', None))
                elif event == 'external_id_write':
                    if record.get('outcome') == 'success' or record.get('reason') in ('locked', 'already_set'):
                        handled.add((entity, tmdb_id, record.get('field')))
    return handled


def pending_targets(record, entity_path, handled):
    targets = {}
    for key, value in record['targets'].items():
        if key == 'wikidata_id':
            if (entity_path, record['tmdb_id'], key, value) in handled or \
               (entity_path, record['tmdb_id'], key, None) in handled:
                continue
        elif (entity_path, record['tmdb_id'], key) in handled:
            continue
        targets[key] = value
    return targets


# =============================================================================
# The external_ids visit
# =============================================================================
def log_external_id_write(context, entity_path, lngid, key, outcome, reason=None, value=None,
                          previous=None, duration_ms=None):
    context = context or {}
    record_id = log_int(lngid)
    append_log_event(
        'external_id_write',
        action='set',
        field=key,
        outcome=outcome,
        reason=reason,
        dry_run=DRY_RUN,
        dataset=context.get('dataset'),
        mode='fill',
        entity=entity_path,
        tmdb_id=record_id,
        name=context.get('name'),
        wikidata_id=context.get('wikidata_id'),
        value=log_value(value),
        previous=log_value(previous),
        url=wd.TMDB_EDIT_URL.format(entity=entity_path, tmdb_id=record_id),
        csv_file=context.get('csv_file'),
        csv_row=log_int(context.get('csv_row')),
        attempt=log_int(context.get('attempt')) or 1,
        duration_ms=duration_ms,
    )


def open_external_ids_patiently(driver, entity_path, lngid):
    """open_edit_page, waiting out TMDb's throttling like the primary facts robot."""
    loaded = open_edit_page(driver, entity_path, lngid)
    for wait in pf.THROTTLE_WAITS:
        if not pf.is_throttled(driver):
            return loaded
        print(f'TMDB throttles (429) on {entity_path} {lngid}: waiting {wait} s.')
        append_log_event('throttled', entity=entity_path, tmdb_id=log_int(lngid), wait_s=wait)
        time.sleep(wait)
        loaded = open_edit_page(driver, entity_path, lngid)
    if pf.is_throttled(driver):
        raise pf.TmdbThrottled(f'TMDB still answers 429 after waiting {sum(pf.THROTTLE_WAITS)} s')
    return loaded


def is_external_field_locked(driver, key):
    return len(driver.find_elements(By.CSS_SELECTOR, f'span#{key}_status.locked')) > 0


def read_external_field(driver, key):
    field = wd.find_visible_element(driver, By.NAME, key)
    return field, (None if field is None else (read_field_value(field) or '').strip())


def set_external_ids(driver, entity_path, lngid, targets, context, mode='fix'):
    """Fill the external_ids tab of one record in one visit.

    Returns 'written', 'skipped', 'no_change' (every field already set or locked on the
    live page: the page answered, which says nothing bad about the browser, so it must
    not feed MAX_CONSECUTIVE_SKIPS; our copy of TheTVDB ids lags behind TMDb) or 'dry_run'.

    wikidata_id keeps the v2 rules (written over an empty or malformed value, over a valid
    one only in replace mode, traced by log_wikidata_write); every other field is filled
    only when empty on the live page. After Save the page is opened again and only a value
    read back counts as success.
    """
    started = time.monotonic()
    previous = {}
    reasons = []

    def trace(key, outcome, reason=None):
        reasons.append(reason)
        duration = int((time.monotonic() - started) * 1000)
        if key == 'wikidata_id':
            wd.log_wikidata_write(dict(context, mode=mode), 'set', lngid, outcome, reason,
                                  wikidata_id=targets.get(key), previous_wikidata_id=previous.get(key),
                                  duration_ms=duration)
        else:
            log_external_id_write(context, entity_path, lngid, key, outcome, reason, targets.get(key),
                                  previous.get(key), duration)

    def trace_all(outcome, reason, keys=None):
        for key in (keys or targets):
            trace(key, outcome, reason)

    if not open_external_ids_patiently(driver, entity_path, lngid):
        trace_all('failed', 'page_load_timeout')
        return 'skipped'
    if is_page_not_found(driver):
        trace_all('skipped', 'page_not_found')
        return 'skipped'
    if not create_english_translation(driver, entity_path, lngid):
        trace_all('failed', 'translation_failed')
        return 'skipped'
    # Every external_ids tab has the wikidata_id field: its absence means the page itself
    # is wrong (logged out, error page), not that one field is missing.
    if wd.get_wikidata_id_field(driver, lngid, f'external_ids tab not found for {entity_path} {{lngid}}.') is None:
        if is_logged_out(driver):
            trace_all('failed', 'session_lost')
            raise BrowserSessionLost('TMDB redirected to the login page')
        trace_all('skipped', 'field_not_found')
        return 'skipped'

    plan = {}
    for key, value in targets.items():
        field, current = read_external_field(driver, key)
        if field is None:
            print(f'{entity_path} {lngid}: no {key} field on the page. Skipping it.')
            trace(key, 'skipped', 'field_not_found')
            continue
        previous[key] = current or None
        if current == value:
            print(f'{entity_path} {lngid}: {key} already {value}.')
            trace(key, 'skipped', 'already_set')
            continue
        if current and key != 'wikidata_id':
            print(f'{entity_path} {lngid}: {key} already {current!r} on TMDB. Skipping it.')
            trace(key, 'skipped', 'already_set')
            continue
        if is_external_field_locked(driver, key):
            print(f'{entity_path} {lngid}: {key} is locked. Skipping it.')
            trace(key, 'skipped', 'locked')
            continue
        if not is_field_writable(field):
            print(f'{entity_path} {lngid}: {key} not editable ({describe_field_state(field)}). Skipping it.')
            trace(key, 'skipped', 'field_not_editable')
            continue
        plan[key] = field

    if not plan:
        return 'no_change' if reasons and all(r in ('already_set', 'locked') for r in reasons) else 'skipped'

    name = context.get('name')
    if DRY_RUN:
        for key in plan:
            print(f'DRY RUN {entity_path} {lngid} {name}: would set {key} {targets[key]}'
                  + (f' (was {previous[key]!r})' if previous.get(key) else '') + '.')
            trace(key, 'skipped', 'dry_run')
        return 'dry_run'

    for key in list(plan):
        try:
            plan[key].clear()
            plan[key].send_keys(targets[key])
            ok = (read_field_value(plan[key]) or '').strip() == targets[key]
        except (InvalidElementStateException, ElementNotInteractableException,
                StaleElementReferenceException) as exc:
            print(f'{entity_path} {lngid}: {key} could not be edited ({type(exc).__name__}).')
            ok = False
        if not ok:
            trace(key, 'skipped', 'field_write_refused')
            del plan[key]
    if not plan:
        return 'skipped'

    any_field = next(iter(plan.values()))
    driver.execute_script(pf.SAVE_TRACKER_JS)
    click_save_button(driver)
    statuses = pf.wait_for_save(driver, any_field)
    if statuses is None:
        print(f'{entity_path} {lngid}: no answer to Save after {pf.SAVE_RELOAD_TIMEOUT} s, reading the page back anyway.')
    elif any(status >= 400 or status == 0 for status in statuses):
        print(f'{entity_path} {lngid}: Save answered {statuses}, reading the page back.')

    # Read back from a fresh page: the fields the robot typed prove nothing (v2 checked the
    # input box only, and logged success for QIDs TMDb had silently refused).
    try:
        reloaded = open_external_ids_patiently(driver, entity_path, lngid)
    except pf.TmdbThrottled:
        trace_all('failed', 'save_not_confirmed', plan)
        raise
    if not reloaded or wd.get_wikidata_id_field(driver, lngid, 'external_ids tab not found after Save.') is None:
        trace_all('failed', 'save_not_confirmed', plan)
        return 'skipped'

    written = []
    for key in plan:
        _, current = read_external_field(driver, key)
        if current != targets[key]:
            print(f'{entity_path} {lngid}: {key} not confirmed, {targets[key]} was not applied (page: {current!r}).')
            trace(key, 'failed', 'save_not_confirmed')
            continue
        trace(key, 'success')
        written.append(f'{key} {targets[key]}')
    if not written:
        return 'skipped'
    print(f"{entity_path} {lngid} updated: {'; '.join(written)}.")
    return 'written'


def visit_record(driver, spec, record, targets, context):
    """The erase (v2 rule: clear the record holding the QID first), then the visit."""
    entity_path = spec['entity_path']
    if 'wikidata_id' in targets and record.get('erase') and not DRY_RUN:
        wd.clear_wikidata_id(driver, entity_path, record['erase'], dict(context, mode=record['mode']))
    return set_external_ids(driver, entity_path, record['tmdb_id'], targets, context, record['mode'] or 'fix')


def visit_with_recovery(driver, spec, record, targets, context):
    """visit_record, restarting Chrome when it dies under the record. Returns (driver, result)."""
    entity_path = spec['entity_path']
    for attempt in range(1, BROWSER_RESTART_ATTEMPTS + 1):
        try:
            return driver, visit_record(driver, spec, record, targets, dict(context, attempt=attempt))
        except BrowserSessionLost as exc:
            reason = str(exc)
        except pf.TmdbThrottled:
            raise
        except Exception as exc:
            if not is_browser_gone(exc):
                raise
            reason = f'{type(exc).__name__}: {exc}'.strip()
        print(f'Browser lost on {entity_path} {record["tmdb_id"]} ({reason}). '
              f'Attempt {attempt}/{BROWSER_RESTART_ATTEMPTS}.')
        if attempt == BROWSER_RESTART_ATTEMPTS:
            break
        driver = restart_browser(driver)
    raise RuntimeError(f'Chrome could not be kept alive for {entity_path} {record["tmdb_id"]} after '
                       f'{BROWSER_RESTART_ATTEMPTS} attempts.')


def process_entity(driver, phase):
    """Walk the merged exports of one entity. Returns the driver in use."""
    spec = ENTITIES[phase]
    entity_path = spec['entity_path']
    fields = [key for key in FILL_FIELDS if key in EXTERNAL_FIELDS]
    worklist, files = build_worklist(spec, fields, REPLACE)
    print(f'{phase}: {len(worklist)} records in {files}, fields {fields}')

    # Cursor: resumes only the same exports and a run covering no new field (the
    # place_of_birth lesson, 2026-11-11). Anything else starts at the top.
    cursor = get_store_value(spec['store_key'], {}) or {}
    start = cursor.get('position', -1)
    if DRY_RUN or cursor.get('files') != files or any(key not in (cursor.get('fields') or []) for key in fields):
        start = -1
    handled = already_handled_external()
    print(f'DRY_RUN={DRY_RUN} MAX_ROWS={MAX_ROWS} start={start} handled={len(handled)}')

    counts = {'written': 0, 'skipped': 0, 'dry_run': 0, 'no_change': 0}
    processed = consecutive_skips = skip_restarts = 0
    started = time.monotonic()
    append_log_event('dataset_start', dataset=f'v3_{phase}', mode='fill', entity=entity_path, dry_run=DRY_RUN,
                     csv_file=files, csv_rows=len(worklist), cursor_key=spec['store_key'], cursor_start=start,
                     max_rows=MAX_ROWS, fields=fields)

    def log_end(status):
        append_log_event('dataset_end', dataset=f'v3_{phase}', mode='fill', entity=entity_path, dry_run=DRY_RUN,
                         csv_file=files, status=status, processed=processed, updated=counts['written'],
                         skipped=counts['skipped'], dry_runs=counts['dry_run'], no_change=counts['no_change'],
                         duration_s=round(time.monotonic() - started, 1))

    try:
        for position, record in enumerate(worklist):
            if position <= start:
                continue
            if MAX_ROWS and processed >= MAX_ROWS:
                print(f'MAX_ROWS={MAX_ROWS} reached.')
                break
            targets = pending_targets(record, entity_path, handled)
            if not targets:
                continue
            context = {'dataset': f'v3_{phase}', 'entity': entity_path, 'name': log_value(record['label']),
                       'wikidata_id': log_value(record['targets'].get('wikidata_id') or record.get('wikidata_qid')),
                       'csv_file': record['csv_file'], 'csv_row': record['csv_row']}
            driver, result = visit_with_recovery(driver, spec, record, targets, context)
            counts[result] += 1
            processed += 1
            if result == 'written':
                consecutive_skips = skip_restarts = 0
            elif result == 'skipped':
                consecutive_skips += 1
            if not DRY_RUN:
                set_store_value(spec['store_key'], {'files': files, 'position': position, 'fields': fields})

            if consecutive_skips >= MAX_CONSECUTIVE_SKIPS:
                if skip_restarts:
                    raise RuntimeError(f'{consecutive_skips} records in a row wrote nothing, and a fresh browser '
                                       'did not change that. The cursor is stored.')
                print(f'{consecutive_skips} records in a row wrote nothing: restarting Chrome.')
                skip_restarts += 1
                consecutive_skips = 0
                driver = restart_browser(driver)
            elif BROWSER_RECYCLE_EVERY and processed % BROWSER_RECYCLE_EVERY == 0:
                print(f'{processed} records processed: recycling Chrome.')
                driver = restart_browser(driver)
            time.sleep(pf.current_pause())
    except pf.TmdbThrottled as exc:
        log_end('throttled')
        print(f'{exc}. The cursor is stored: the run waits, then resumes there.')
        raise
    except BaseException:
        log_end('aborted')
        raise
    log_end('completed')
    print(f"{phase} done: {counts['written']} written, {counts['skipped']} skipped, "
          f"{counts['no_change']} already set on TMDB, {counts['dry_run']} dry run.")
    return driver


def process_primary_facts(driver):
    """The primary facts phase: the v2 engine, with v3's settings and logs."""
    pf.DRY_RUN = DRY_RUN
    pf.MAX_ROWS = MAX_ROWS
    pf.FILL_FIELDS = [key for key in FILL_FIELDS if key in pf.PRIMARY_FIELDS]
    if not pf.FILL_FIELDS:
        return driver
    return pf.process_primary_facts(driver)


# =============================================================================
# Diagnostic (read-only)
# =============================================================================
def debug_external_ids_page(driver, entity_path, lngid):
    """Dump the external_ids tab of one record. Read-only: nothing is written to TMDB."""
    open_edit_page(driver, entity_path, lngid)
    time.sleep(3)
    print(f'url    : {driver.current_url}')
    print(f'title  : {driver.title}')
    print(f'404    : {is_page_not_found(driver)}  logged out: {is_logged_out(driver)}  throttled: {pf.is_throttled(driver)}')
    for key in EXTERNAL_FIELDS:
        field, current = read_external_field(driver, key)
        state = 'absent' if field is None else describe_field_state(field)
        print(f'{key:13}: {current!r:30} locked={is_external_field_locked(driver, key)} {state}')


# =============================================================================
# Main
# =============================================================================
def main():
    global DRY_RUN, MAX_ROWS, FILL_FIELDS, REPLACE

    parser = argparse.ArgumentParser(description='Everything the robot writes on TMDb, in a real Chrome (v3).')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--diagnostic', nargs=2, metavar=('ENTITY', 'TMDB_ID'),
                        help='read-only: the external_ids tab of one record (ENTITY: movie, tv or person)')
    action.add_argument('--reset-cursors', action='store_true', help='the next run starts every phase at the top')
    parser.add_argument('--phases', nargs='+', choices=PHASES, default=PHASES, metavar='PHASE',
                        help=f'phases to run, in order (default: {" ".join(PHASES)})')
    parser.add_argument('--fields', nargs='+', choices=EXTERNAL_FIELDS + list(pf.PRIMARY_FIELDS),
                        default=DEFAULT_FIELDS, metavar='FIELD',
                        help=f'fields to fill (default: {" ".join(DEFAULT_FIELDS)}; youtube_id only on request)')
    parser.add_argument('--replace', action='store_true',
                        help='also OVERWRITE valid QIDs from the wikidata-id-*-replace exports (destructive)')
    parser.add_argument('--dry-run', action='store_true', help='pages checked, nothing saved')
    parser.add_argument('--max-rows', type=int, default=0, help='records per phase, 0 for no limit (default: 0)')
    args = parser.parse_args()

    if args.reset_cursors:
        for spec in ENTITIES.values():
            set_store_value(spec['store_key'], {})
        set_store_value(pf.PRIMARY_FACTS_DATASET['store_key'], {})
        print('Cursors reset.')
        return

    driver = None
    try:
        if args.diagnostic:
            entity_path, lngid = args.diagnostic
            if entity_path not in ENTITIES:
                parser.error('ENTITY must be movie, tv or person')
            driver = init_driver()
            login_tmdb(driver)
            debug_external_ids_page(driver, entity_path, int(lngid))
            return

        DRY_RUN, MAX_ROWS, FILL_FIELDS, REPLACE = args.dry_run, args.max_rows, list(args.fields), args.replace
        print(f'v3: phases {args.phases}, fields {FILL_FIELDS}, dry run {DRY_RUN}, replace {REPLACE}, '
              f'max rows {MAX_ROWS or "no limit"}')

        state = {'driver': None, 'attempts': 0, 'done': 0}

        def attempt():
            state['attempts'] += 1
            download_exports(args.phases, REPLACE)
            if state['attempts'] == 1:
                state['driver'] = init_driver()
                login_tmdb(state['driver'])
            else:
                state['driver'] = replace_browser(state['driver'])
            while state['done'] < len(args.phases):
                phase = args.phases[state['done']]
                if phase == 'primary_facts':
                    state['driver'] = process_primary_facts(state['driver'])
                else:
                    state['driver'] = process_entity(state['driver'], phase)
                state['done'] += 1

        try:
            run_until_done(attempt, 'v3', throttled_types=(pf.TmdbThrottled,))
        finally:
            driver = state['driver']
    finally:
        close_browser_when_done(driver)


if __name__ == '__main__':
    main()
