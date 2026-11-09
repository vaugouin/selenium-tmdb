#!/usr/bin/env python
"""Write Wikidata QIDs into the wikidata_id external ID of TMDb records (v2).

Copy of selenium-tmdb-wikidata_id.py: the shared code lives in
selenium_tmdb_common.py, and Chrome is a real one on a persistent profile that
keeps the TMDB session (log in once by hand, see README). Every run MODIFIES
LIVE RECORDS on themoviedb.org: run it deliberately, in a terminal, while
watching the browser (never from CI or cron).

    python selenium-tmdb-wikidata_id-v2.py                    # cells 5, 7, 8: movies, series, persons (fix)
    python selenium-tmdb-wikidata_id-v2.py --datasets 3 4 5   # the replace datasets
    python selenium-tmdb-wikidata_id-v2.py --diagnostic movie 300115
    python selenium-tmdb-wikidata_id-v2.py --reset-cursors
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

selenium_tmdb_common.LOG_BASENAME = 'selenium-tmdb-wikidata_id'

# =============================================================================
# Notebook cell 3: DATASETS
# =============================================================================
DATASETS = [
    {
        'name': 'movies',
        'remote_folder': 'wikidata-id-movie-fix',
        'local_folder': 'wikidata-id-movie-fix',
        'local_file_basename': 'wikidata-id-movie-fix',
        'mode': 'fix',
        'entity_path': 'movie',
        'id_column': 'ID_MOVIE',
        'erase_column': 'ID_MOVIE_ERASE_WIKIDATA_ID',
        'store_key': 'lngmovieidstart',
        'missing_entity_message': 'Colonne ID_MOVIE manquante dans le fichier CSV',
        'missing_wikidata_message': 'Colonne ID_WIKIDATA manquante dans le fichier CSV',
        'timeout_message': 'wikidata_id field not found for movie {lngid}. Skipping.'
    },
    {
        'name': 'series',
        'remote_folder': 'wikidata-id-serie-fix',
        'local_folder': 'wikidata-id-serie-fix',
        'local_file_basename': 'wikidata-id-serie-fix',
        'mode': 'fix',
        'entity_path': 'tv',
        'id_column': 'ID_SERIE',
        'erase_column': 'ID_SERIE_ERASE_WIKIDATA_ID',
        'store_key': 'lngserieidstart',
        'missing_entity_message': 'Colonne ID_SERIE manquante dans le fichier CSV',
        'missing_wikidata_message': 'Colonne ID_WIKIDATA manquante dans le fichier CSV',
        'timeout_message': 'wikidata_id field not found for serie {lngid}. Skipping.'
    },
    {
        'name': 'persons',
        'remote_folder': 'wikidata-id-person-fix',
        'local_folder': 'wikidata-id-person-fix',
        'local_file_basename': 'wikidata-id-person-fix',
        'mode': 'fix',
        'entity_path': 'person',
        'id_column': 'ID_PERSON',
        'erase_column': 'ID_PERSON_ERASE_WIKIDATA_ID',
        'store_key': 'lngpersonidstart',
        'missing_entity_message': 'Colonne ID_PERSON manquante dans le fichier CSV',
        'missing_wikidata_message': 'Colonne ID_WIKIDATA manquante dans le fichier CSV',
        'timeout_message': 'wikidata_id field not found for person {lngid}. Skipping.',
        'intgoingdown': True
    },
    # ------------------------------------------------------------------
    # LES TROIS JEUX DE REMPLACEMENT, ajoutes le 2026-09-05.
    #
    # Les trois premiers REMPLISSENT une case wikidata_id vide ou illisible.
    # Ceux-ci REMPLACENT une valeur valide par une autre, ce qui detruit de
    # l'information sur un site tiers au lieu d'en ajouter. Leur source est
    # wikidata-id-<entite>-replace.sql, qui n'exporte que les cas ou Wikidata
    # designe elle-meme la fiche TMDb visee (garde 3 : la corroboration).
    #
    # Jeux SEPARES et non lignes supplementaires dans les fichiers -fix, pour
    # que l'on puisse lancer les remplissages sans les remplacements, mesurer
    # les deux populations a part, et interrompre l'un sans perdre le curseur
    # de l'autre. D'ou aussi des store_key distincts.
    #
    # Volumetrie attendue, mesuree le 2026-09-05 sur les films : 659 fiches,
    # contre 19 196 pour le remplissage. Le passage est donc court.
    # ------------------------------------------------------------------
    {
        'name': 'movies_replace',
        'remote_folder': 'wikidata-id-movie-replace',
        'local_folder': 'wikidata-id-movie-replace',
        'local_file_basename': 'wikidata-id-movie-replace',
        'mode': 'replace',
        'entity_path': 'movie',
        'id_column': 'ID_MOVIE',
        'erase_column': 'ID_MOVIE_ERASE_WIKIDATA_ID',
        'store_key': 'lngmoviereplaceidstart',
        'missing_entity_message': 'Colonne ID_MOVIE manquante dans le fichier CSV',
        'missing_wikidata_message': 'Colonne ID_WIKIDATA manquante dans le fichier CSV',
        'timeout_message': 'wikidata_id field not found for movie {lngid}. Skipping.'
    },
    {
        'name': 'series_replace',
        'remote_folder': 'wikidata-id-serie-replace',
        'local_folder': 'wikidata-id-serie-replace',
        'local_file_basename': 'wikidata-id-serie-replace',
        'mode': 'replace',
        'entity_path': 'tv',
        'id_column': 'ID_SERIE',
        'erase_column': 'ID_SERIE_ERASE_WIKIDATA_ID',
        'store_key': 'lngseriereplaceidstart',
        'missing_entity_message': 'Colonne ID_SERIE manquante dans le fichier CSV',
        'missing_wikidata_message': 'Colonne ID_WIKIDATA manquante dans le fichier CSV',
        'timeout_message': 'wikidata_id field not found for serie {lngid}. Skipping.'
    },
    {
        'name': 'persons_replace',
        'remote_folder': 'wikidata-id-person-replace',
        'local_folder': 'wikidata-id-person-replace',
        'local_file_basename': 'wikidata-id-person-replace',
        'mode': 'replace',
        'entity_path': 'person',
        'id_column': 'ID_PERSON',
        'erase_column': 'ID_PERSON_ERASE_WIKIDATA_ID',
        'store_key': 'lngpersonreplaceidstart',
        'missing_entity_message': 'Colonne ID_PERSON manquante dans le fichier CSV',
        'missing_wikidata_message': 'Colonne ID_WIKIDATA manquante dans le fichier CSV',
        'timeout_message': 'wikidata_id field not found for person {lngid}. Skipping.'
    }
]

# =============================================================================
# Notebook helper cell, wikidata_id only (the rest is in selenium_tmdb_common.py)
# =============================================================================
TMDB_EDIT_URL = 'https://www.themoviedb.org/{entity}/{tmdb_id}/edit?active_nav_item=external_ids'

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
# Notebook cells 5 to 9
# =============================================================================
# Cell 9 of the notebook, the six cursors it resets.
STORE_KEYS = ('lngmovieidstart', 'lngserieidstart', 'lngpersonidstart', 'lngmoviereplaceidstart', 'lngseriereplaceidstart', 'lngpersonreplaceidstart')


def main():
    parser = argparse.ArgumentParser(description='Write Wikidata QIDs into TMDb, in a real Chrome (v2).')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--diagnostic', nargs='*', metavar='ARG',
                        help="read-only: ENTITY TMDB_ID (default: movie 300115)")
    action.add_argument('--reset-cursors', action='store_true', help='reset the six cursors to 0')
    parser.add_argument('--datasets', type=int, nargs='+', default=[0, 1, 2], choices=range(len(DATASETS)),
                        metavar='N', help='DATASETS entries to process, in order (default: 0 1 2, the fill datasets; 3 4 5 replace)')
    args = parser.parse_args()

    if args.diagnostic is not None and len(args.diagnostic) not in (0, 2):
        parser.error('--diagnostic takes ENTITY TMDB_ID, or nothing')

    if args.reset_cursors:
        # Cell 9
        for key in STORE_KEYS:
            set_store_value(key, 0)
        return

    driver = None
    try:
        if args.diagnostic is not None:
            # Cell 5
            for dataset in DATASETS:
                download_new_csv_files(dataset['remote_folder'], dataset['local_folder'])
            driver = init_driver()
            login_tmdb(driver)
            # Cell 6
            entity_path, lngid = args.diagnostic or ['movie', '300115']
            debug_wikidata_page(driver, entity_path, int(lngid))
            return

        # Cells 5 and 7 under run_until_done: an error never ends the run. It waits,
        # downloads the exports again, takes a fresh browser and resumes the dataset it
        # was on from its stored cursor; the datasets already finished are not redone.
        # process_dataset returns the driver in use: Chrome is restarted in place when
        # it crashes, and the old session dies with it.
        state = {'driver': None, 'attempts': 0, 'done': 0}

        def attempt():
            state['attempts'] += 1
            for dataset in DATASETS:
                download_new_csv_files(dataset['remote_folder'], dataset['local_folder'])
            if state['attempts'] == 1:
                state['driver'] = init_driver()
                login_tmdb(state['driver'])
            else:
                state['driver'] = replace_browser(state['driver'])
            while state['done'] < len(args.datasets):
                state['driver'] = process_dataset(state['driver'], DATASETS[args.datasets[state['done']]])
                state['done'] += 1

        try:
            run_until_done(attempt, 'wikidata_id')
        finally:
            driver = state['driver']

        # Cell 8
        # Loop is finished so we display the home page
        open_page(driver, 'https://www.themoviedb.org/')
    finally:
        close_browser_when_done(driver)


if __name__ == '__main__':
    main()
