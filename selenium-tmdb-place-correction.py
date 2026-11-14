"""Correct the Places of Birth the robot wrote with today's country (2026-11-11 to 11-13).

TMDb's rule (People Bible, Place of Birth): "The place of birth should reflect the names
and political divisions used at the time of birth", today's name in brackets: "Brno,
Czechoslovakia [now Czech Republic]". The primary facts export wrote the country of today
("Brno, Czech Republic") for people born in Czechoslovakia, the USSR, Yugoslavia, East or
West Germany, Austria-Hungary; a TMDb contributor reported it on 2026-11-13.

Two steps:

1. --build (read-only on TMDb): reads every place_of_birth the robot wrote, from the logs,
   and the database (through the SFTP server's SSH tunnel, credentials of preprocess/.env):
   the person's birth date, the place's country and region in Wikidata, and the defunct
   countries and successions of T_WC_COUNTRY / T_WC_COUNTRY_SUCCESSION (tmdb-person-preprocess,
   migrations/add_defunct_countries.py). Writes the records to correct to
   data/place-of-birth-correction/place-of-birth-correction-YYYYMMDD.csv:
   - REPLACE: the country of the time is known, and the historical form of the place is
     already used by PLACE_USES_MIN persons on TMDb ("Písek, Czechoslovakia [now Czech
     Republic]"). The form must be used by others because the database does not know
     renamed cities: "Saint Petersburg, USSR" would be wrong for Leningrad.
   - CLEAR: any other record the rule says should not have been written (country of the
     time known but no such form, country of the time unknown, birth date unknown in a
     country whose borders moved). The field was empty before the robot wrote it.

2. The run (writes on TMDb, --dry-run to only check): for each row, opens the primary_facts
   tab; skips the person when the field is locked or no longer shows what the robot wrote
   (someone changed it since); otherwise replaces (the exact place of TMDb's list, else it
   clears) or clears it, saves, reads it back from a fresh page.

Every attempt is a place_of_birth_correction line in logs/selenium-tmdb-place-correction-
YYYYMMDD.log; a person already corrected, locked or changed by someone is not opened again.
An error never ends the run (run_until_done). The primary facts robots never write these
places again: their earlier success stays in their logs (already_handled_fields).
"""

import argparse
import csv
import importlib.util
import json
import os
import socket
import select
import threading
import time
from datetime import date, datetime
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)

import selenium_tmdb_common
from selenium_tmdb_common import *


def load_script(file_name, module_name):
    spec = importlib.util.spec_from_file_location(module_name, Path(__file__).resolve().parent / file_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pf = load_script('selenium-tmdb-deathday-v2.py', 'primary_facts_v2')

LOG_BASENAME = 'selenium-tmdb-place-correction'
selenium_tmdb_common.LOG_BASENAME = LOG_BASENAME
pf.LOG_BASENAME = LOG_BASENAME

# =============================================================================
# Settings
# =============================================================================
DRY_RUN = False
MAX_ROWS = 0
PLACE_USES_MIN = 3        # persons on TMDb already using a historical form before it is written
CORRECTION_DIR = Path('./data/place-of-birth-correction')
EVENT = 'place_of_birth_correction'
FIELD = 'place_of_birth'
# Outcomes that close a person for good: corrected, or not ours to touch any more.
HANDLED_REASONS = ('locked', 'changed_by_other', 'page_not_found')


# =============================================================================
# Database, read-only, through the SSH connection of the SFTP account
# =============================================================================
def open_database():
    """A pymysql connection to the VPS's MariaDB, tunnelled through SSH. Returns (connection, ssh client)."""
    import pymysql
    from dotenv import dotenv_values

    env = dotenv_values('preprocess/.env')
    missing = [key for key in ('DB_USER', 'DB_PASSWORD', 'DB_NAME') if not env.get(key)]
    if missing:
        raise ValueError(f'preprocess/.env lacks {", ".join(missing)}: the list cannot be built.')
    client, sftp = open_sftp_connection()
    sftp.close()
    transport = client.get_transport()
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen(5)

    def pump(local, channel):
        try:
            while True:
                ready, _, _ = select.select([local, channel], [], [])
                for sock in ready:
                    data = sock.recv(65536)
                    if not data:
                        return
                    (channel if sock is local else local).sendall(data)
        except (OSError, EOFError, paramiko.SSHException):
            pass   # either end closed

    def serve():
        try:
            while True:
                local, address = server.accept()
                channel = transport.open_channel('direct-tcpip', ('127.0.0.1', int(env.get('DB_PORT') or 3306)), address)
                threading.Thread(target=pump, args=(local, channel), daemon=True).start()
        except (OSError, EOFError, paramiko.SSHException):
            return   # the SSH connection was closed: the tunnel ends with it

    threading.Thread(target=serve, daemon=True).start()
    connection = pymysql.connect(host='127.0.0.1', port=server.getsockname()[1], user=env['DB_USER'],
                                 password=env['DB_PASSWORD'], database=env['DB_NAME'], charset='utf8mb4',
                                 connect_timeout=20, read_timeout=900,
                                 cursorclass=pymysql.cursors.DictCursor)
    return connection, client


def query(connection, sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def chunks(values, size=1000):
    values = list(values)
    for start in range(0, len(values), size):
        yield values[start:start + size]


def in_list(values):
    return ', '.join(['%s'] * len(values))


# =============================================================================
# The rule: country of the time, from T_WC_COUNTRY_SUCCESSION
# =============================================================================
class History:
    """Countries and successions, read once. Mirrors the rule of migrations/add_defunct_countries.py."""

    def __init__(self, connection):
        rows = query(connection, 'SELECT COUNTRY_CODE, ID_WIKIDATA, DAT_START, PLACE_NAME_EN, IS_DEFUNCT '
                                 'FROM T_WC_COUNTRY WHERE COUNTRY_CODE IS NOT NULL')
        self.by_qid = {r['ID_WIKIDATA']: r['COUNTRY_CODE'].upper() for r in rows
                       if r['ID_WIKIDATA'] and not r['IS_DEFUNCT']}
        self.country = {r['COUNTRY_CODE'].upper(): r for r in rows}
        self.succession = {}
        for r in query(connection, 'SELECT * FROM T_WC_COUNTRY_SUCCESSION WHERE COALESCE(DELETED, 0) = 0 '
                                   'ORDER BY DISPLAY_ORDER'):
            self.succession.setdefault(r['COUNTRY_CODE'].upper(), []).append(r)

    def covers(self, code):
        """Whether today's country has a history the rule knows about (rows or a start date)."""
        return bool(self.succession.get(code) or (self.country.get(code) or {}).get('DAT_START'))

    def at(self, code, day, regions):
        """Country code at the date, or None when it cannot be told from the country alone."""
        for row in self.succession.get(code, []):
            if row['DAT_START'] <= day <= row['DAT_END']:
                if row['REGION_QIDS']:
                    if not regions:
                        return None
                    if not regions & set(row['REGION_QIDS'].split(',')):
                        continue
                return (row['COUNTRY_CODE_AT_BIRTH'] or '').upper() or None
        start = (self.country.get(code) or {}).get('DAT_START')
        return code if not start or start <= day else None

    def at_birth(self, code, birthday, birth_year, regions):
        """('ok' | 'wrong' | 'unknown' | 'no_date', country of the time)."""
        if birthday:
            found = self.at(code, birthday, regions)
        elif birth_year:
            first, last = (self.at(code, date(birth_year, 1, 1), regions),
                           self.at(code, date(birth_year, 12, 31), regions))
            found = first if first == last else None
        else:
            return ('no_date', None) if self.covers(code) else ('ok', code)
        if found is None:
            return 'unknown', None
        return ('ok' if found == code else 'wrong'), found

    def changed_since_1950(self, code):
        """Whether the country's history reaches past 1950: without a birth date, a person of
        today's Germany or Czech Republic may have been born in East Germany or Czechoslovakia;
        a person of today's Italy or Austria (rows before 1945) is almost surely modern."""
        limit = date(1950, 1, 1)
        start = (self.country.get(code) or {}).get('DAT_START')
        return bool((start and start >= limit) and self.succession.get(code)) or any(
            row['DAT_END'] >= limit for row in self.succession.get(code, []))

    def place_name(self, code):
        return (self.country.get(code) or {}).get('PLACE_NAME_EN')


def historical_forms(written, historic_name):
    """The spellings TMDb contributors use for the same place at the time, best first."""
    parts = [part.strip() for part in written.split(',')]
    current, head = parts[-1], parts[:-1]
    forms = []
    for kept in (head, head[:1]):
        if kept:
            forms.append(', '.join(kept + [historic_name]) + f' [now {current}]')
    for kept in (head, head[:1]):
        if kept:
            forms.append(', '.join(kept + [historic_name]))
    return list(dict.fromkeys(forms))


# =============================================================================
# Step 1: the list (read-only)
# =============================================================================
def logged_place_writes():
    """{tmdb_id: {'value', 'wikidata_id', 'ts'}} of every place_of_birth a real run wrote."""
    writes = {}
    for path in sorted(LOG_DIR.glob('selenium-tmdb*.log')):
        if path.name.startswith(LOG_BASENAME):
            continue
        with path.open(encoding='utf-8') as log_file:
            for line in log_file:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if (record.get('event') == 'primary_fact_write' and record.get('field') == FIELD
                        and record.get('outcome') == 'success' and not record.get('dry_run')):
                    writes[int(record['tmdb_id'])] = {'value': record.get('value'),
                                                      'wikidata_id': record.get('wikidata_id'),
                                                      'ts': record.get('ts')}
    return writes


def best_items(connection, qids, prop):
    """{qid: set of item values} of a property, best values only, not deprecated nor deleted."""
    found = {}
    for part in chunks(qids):
        for r in query(connection,
                       'SELECT s.ID_WIKIDATA, v.ID_ITEM FROM T_WC_WIKIDATA_STATEMENT s '
                       'JOIN T_WC_WIKIDATA_ITEM_VALUE v ON v.ID_STATEMENT = s.ID_STATEMENT '
                       f'WHERE s.ID_PROPERTY = %s AND s.ID_WIKIDATA IN ({in_list(part)}) '
                       "AND (s.`RANK` IS NULL OR s.`RANK` <> 'deprecated') AND COALESCE(s.DELETED, 0) = 0 "
                       'AND COALESCE(s.IS_BEST_VALUE, 1) = 1', [prop] + part):
            found.setdefault(r['ID_WIKIDATA'], set()).add(r['ID_ITEM'])
    return found


WDQS_URL = 'https://query.wikidata.org/sparql'
WDQS_AGENT = 'selenium-tmdb/1.0 (place of birth correction, read-only)'


def wikidata_regions(places, history):
    """{place: set of the succession table's region QIDs it lies in}, through wdt:P131*
    (truthy statements: deprecated ones are left out). Read-only, query.wikidata.org."""
    import requests

    wanted = sorted({qid for rows in history.succession.values() for row in rows if row['REGION_QIDS']
                     for qid in row['REGION_QIDS'].split(',')})
    # '_located' marks a place Wikidata answered for: an empty answer then means "in none
    # of the regions" (a Moscow birth is not in Kaliningrad Oblast), not "region unknown".
    found = {place: {'_located'} for place in places}
    session = requests.Session()
    session.headers['User-Agent'] = WDQS_AGENT
    for part in chunks(places, 200):
        sparql = ('SELECT ?place ?region WHERE { VALUES ?place { %s } VALUES ?region { %s } '
                  '?place wdt:P131* ?region . }') % (' '.join('wd:' + p for p in part), ' '.join('wd:' + q for q in wanted))
        for attempt in range(4):
            answer = session.post(WDQS_URL, data={'query': sparql}, timeout=120,
                                  headers={'Accept': 'application/sparql-results+json'})
            if answer.status_code == 200:
                break
            time.sleep(10 * (attempt + 1))
        answer.raise_for_status()
        for binding in answer.json()['results']['bindings']:
            found[binding['place']['value'].rsplit('/', 1)[1]].add(binding['region']['value'].rsplit('/', 1)[1])
        time.sleep(1)
    print(f'{len(places)} places located in their region (Wikidata), {sum(1 for v in found.values() if len(v) > 1)} in a listed region.')
    return found


def build_list():
    writes = logged_place_writes()
    print(f'{len(writes)} places of birth written by the robot (logs).')
    connection, client = open_database()
    try:
        history = History(connection)
        persons = {}
        for part in chunks(writes):
            for r in query(connection, 'SELECT ID_PERSON, NAME, BIRTHDAY, BIRTH_YEAR, PLACE_OF_BIRTH '
                                       f'FROM T_WC_TMDB_PERSON WHERE ID_PERSON IN ({in_list(part)})', part):
                persons[r['ID_PERSON']] = r
        qids = sorted({w['wikidata_id'] for w in writes.values() if w['wikidata_id']})
        place_of = {q: next(iter(v)) for q, v in best_items(connection, qids, 'P19').items() if len(v) == 1}
        places = sorted(set(place_of.values()))
        country_of = {p: next(iter(v)) for p, v in best_items(connection, places, 'P17').items() if len(v) == 1}
        # Region of the places whose country has region rows (Germany, Russia, Italy), from
        # Wikidata itself: the database's P131 chain is often cut (Nordhausen's link to
        # Thuringia is deprecated, and its district has no P131 in the database).
        region_places = sorted(p for p in places if any(
            row['REGION_QIDS'] for row in history.succession.get(history.by_qid.get(country_of.get(p)), [])))
        regions = wikidata_regions(region_places, history)
        uses ={r['PLACE_OF_BIRTH']: r['n'] for r in query(
            connection, "SELECT PLACE_OF_BIRTH, COUNT(*) AS n FROM T_WC_TMDB_PERSON "
                        "WHERE COALESCE(PLACE_OF_BIRTH, '') <> '' GROUP BY PLACE_OF_BIRTH HAVING COUNT(*) >= %s",
            [PLACE_USES_MIN])}
    finally:
        connection.close()
        client.close()

    rows, counts = [], {}
    for tmdb_id, write in sorted(writes.items()):
        person = persons.get(tmdb_id) or {}
        place = place_of.get(write['wikidata_id'])
        code = history.by_qid.get(country_of.get(place))
        if code is None:
            counts['country unknown to T_WC_COUNTRY, left'] = counts.get('country unknown to T_WC_COUNTRY, left', 0) + 1
            continue
        birthday = person.get('BIRTHDAY')
        birthday = birthday.date() if isinstance(birthday, datetime) else birthday
        verdict, at_birth = history.at_birth(code, birthday, person.get('BIRTH_YEAR'), regions.get(place, set()))
        if verdict == 'ok':
            counts['ok'] = counts.get('ok', 0) + 1
            continue
        if verdict != 'ok' and not history.succession.get(code):
            # Only a start date (Australia 1901, Cambodia 1953, India 1947): the writer will no
            # longer write such births, but Wikidata's inception is sometimes a change of regime
            # (Ethiopia 1974), and TMDb commonly writes these places with today's country.
            # Not cleared: the correction covers the borders of the succession table.
            key = 'country with a start date only, left'
            counts[key] = counts.get(key, 0) + 1
            continue
        if verdict == 'no_date' and not history.changed_since_1950(code):
            # A start date alone (Canada 1867, India 1947...), or borders that moved before 1950
            # (Italy, Austria, Poland), does not make a person without a birth date doubtful.
            key = 'no birth date, country unchanged since 1950, left'
            counts[key] = counts.get(key, 0) + 1
            continue
        new_value = ''
        if verdict == 'wrong' and history.place_name(at_birth):
            forms = [form for form in historical_forms(write['value'], history.place_name(at_birth))
                     if uses.get(form, 0) >= PLACE_USES_MIN]
            new_value = forms[0] if forms else ''
        action = 'REPLACE' if new_value else 'CLEAR'
        counts[f'{verdict} -> {action}'] = counts.get(f'{verdict} -> {action}', 0) + 1
        rows.append({'ID_PERSON': tmdb_id, 'NAME': person.get('NAME') or '', 'ID_WIKIDATA': write['wikidata_id'],
                     'WRITTEN': write['value'], 'ACTION': action, 'NEW_VALUE': new_value,
                     'COUNTRY': code, 'COUNTRY_AT_BIRTH': at_birth or '', 'VERDICT': verdict,
                     'BIRTHDAY': birthday or person.get('BIRTH_YEAR') or '', 'TMDB_COPY': person.get('PLACE_OF_BIRTH') or '',
                     'WRITTEN_AT': write['ts']})

    CORRECTION_DIR.mkdir(parents=True, exist_ok=True)
    path = CORRECTION_DIR / f'place-of-birth-correction-{date.today():%Y%m%d}.csv'
    with path.open('w', encoding='utf-8', newline='') as out:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]) if rows else ['ID_PERSON'], delimiter=';')
        writer.writeheader()
        writer.writerows(rows)
    for key, value in sorted(counts.items()):
        print(f'  {key}: {value}')
    print(f'{len(rows)} records to correct: {path}')


# =============================================================================
# Step 2: the corrections on TMDb
# =============================================================================
PLACE_CLEAR_JS = """
const el = arguments[0];
const w = window.jQuery && jQuery(el).data('kendoAutoComplete');
if (!w) return false;
w.close();
w.value('');
jQuery('#' + el.id + '_id').val('');
jQuery('#' + el.id + '_selected').val('');
return el.value === '' && jQuery('#' + el.id + '_id').val() === '';
"""


def log_correction(row, action, outcome, reason=None, found=None, started=None, attempt=1):
    append_log_event(EVENT, action=action.lower(), field=FIELD, outcome=outcome, reason=reason, dry_run=DRY_RUN,
                     entity='person', tmdb_id=log_int(row['ID_PERSON']), name=row.get('NAME'),
                     wikidata_id=row.get('ID_WIKIDATA'), written=row['WRITTEN'],
                     value=log_value(row['NEW_VALUE'] or None), found=log_value(found),
                     country=row.get('COUNTRY'), country_at_birth=row.get('COUNTRY_AT_BIRTH') or None,
                     url=pf.PRIMARY_FACTS_URL.format(tmdb_id=row['ID_PERSON']), csv_file=row.get('csv_file'),
                     csv_row=log_int(row.get('csv_row')), attempt=attempt,
                     duration_ms=int((time.monotonic() - started) * 1000) if started else None)


def already_corrected():
    done = set()
    for path in LOG_DIR.glob(f'{LOG_BASENAME}-*.log'):
        with path.open(encoding='utf-8') as log_file:
            for line in log_file:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record.get('event') != EVENT or record.get('dry_run'):
                    continue
                if record.get('outcome') == 'success' or record.get('reason') in HANDLED_REASONS:
                    done.add(record.get('tmdb_id'))
    return done


def correct_one(driver, row, attempt=1):
    """Correct one person. Returns 'corrected', 'skipped', 'failed' or 'dry_run'."""
    started = time.monotonic()
    lngid = int(row['ID_PERSON'])
    action = row['ACTION']

    def trace(outcome, reason=None, found=None, done_action=None):
        log_correction(row, done_action or action, outcome, reason, found, started, attempt)

    if not pf.open_primary_facts_patiently(driver, lngid):
        trace('failed', 'page_load_timeout')
        return 'failed'
    if is_page_not_found(driver):
        trace('skipped', 'page_not_found')
        return 'skipped'
    if '/translate/' in driver.current_url:
        trace('skipped', 'translation_missing')
        return 'skipped'
    if pf.get_primary_field(driver, 'deathday', timeout=10) is None:
        if is_logged_out(driver):
            trace('failed', 'session_lost')
            raise BrowserSessionLost('TMDB redirected to the login page')
        trace('failed', 'field_not_found')
        return 'failed'
    field = pf.get_primary_field(driver, FIELD)
    if field is None:
        trace('failed', 'field_not_found')
        return 'failed'
    current = pf.page_value(FIELD, read_field_value(field))
    written = ' '.join(row['WRITTEN'].split())
    if current != written:
        print(f'person {lngid}: Place of Birth is now {current!r}, not what the robot wrote ({written!r}). Left alone.')
        trace('skipped', 'changed_by_other', current)
        return 'skipped'
    if pf.is_primary_field_locked(driver, FIELD):
        print(f'person {lngid}: Place of Birth is locked. Left alone.')
        trace('skipped', 'locked', current)
        return 'skipped'

    target = ' '.join(row['NEW_VALUE'].split()) if action == 'REPLACE' else None
    if DRY_RUN:
        if target:
            try:
                pf.find_place(driver, field, target)
            except pf.PlaceNotFound as exc:
                print(f'DRY RUN person {lngid}: {exc}. Would clear {written!r}.')
                trace('skipped', 'dry_run', current, 'CLEAR')
                return 'dry_run'
            print(f'DRY RUN person {lngid}: would replace {written!r} by {target!r}.')
        else:
            print(f'DRY RUN person {lngid}: would clear {written!r}.')
        trace('skipped', 'dry_run', current)
        return 'dry_run'

    reason = None
    if target:
        try:
            if not pf.write_place_field(driver, field, target):
                trace('failed', 'field_write_refused', current)
                return 'failed'
        except pf.PlaceNotFound as exc:
            print(f'person {lngid}: {exc}. Clearing instead.')
            action, target, reason = 'CLEAR', None, 'replacement_not_found'
    if target is None and not driver.execute_script(PLACE_CLEAR_JS, field):
        trace('failed', 'field_write_refused', current)
        return 'failed'

    driver.execute_script(pf.SAVE_TRACKER_JS)
    click_save_button(driver)
    pf.wait_for_save(driver, field)
    if not pf.open_primary_facts_patiently(driver, lngid) or pf.get_primary_field(driver, FIELD, timeout=10) is None:
        trace('failed', 'save_not_confirmed', current, action)
        return 'failed'
    after = pf.page_value(FIELD, read_field_value(pf.get_primary_field(driver, FIELD)))
    if after != target:
        print(f'person {lngid}: Place of Birth reads {after!r} after Save, expected {target!r}.')
        trace('failed', 'save_not_confirmed', after, action)
        return 'failed'
    print(f'person {lngid}: {written!r} -> {target or "(empty)"!r}.')
    trace('success', reason, after, action)
    return 'corrected'


def correct_with_recovery(driver, row):
    for attempt in range(1, BROWSER_RESTART_ATTEMPTS + 1):
        try:
            return driver, correct_one(driver, row, attempt)
        except BrowserSessionLost as exc:
            reason = str(exc)
        except pf.TmdbThrottled:
            raise
        except Exception as exc:
            if not is_browser_gone(exc):
                raise
            reason = f'{type(exc).__name__}: {exc}'.strip()
        print(f'Browser lost on person {row["ID_PERSON"]} ({reason}). Attempt {attempt}/{BROWSER_RESTART_ATTEMPTS}.')
        if attempt < BROWSER_RESTART_ATTEMPTS:
            driver = restart_browser(driver)
    raise RuntimeError(f'Chrome could not be kept alive for person {row["ID_PERSON"]}.')


def latest_list():
    files = sorted(CORRECTION_DIR.glob('place-of-birth-correction-*.csv'))
    if not files:
        raise FileNotFoundError(f'No list in {CORRECTION_DIR}: run with --build first.')
    return files[-1]


def process_list(driver):
    path = latest_list()
    with path.open(encoding='utf-8') as source:
        rows = list(csv.DictReader(source, delimiter=';'))
    done = set() if DRY_RUN else already_corrected()
    todo = []
    for number, row in enumerate(rows, 1):
        if int(row['ID_PERSON']) not in done:
            todo.append(dict(row, csv_file=path.name, csv_row=number))
    if MAX_ROWS:
        todo = todo[:MAX_ROWS]
    print(f'{path.name}: {len(rows)} rows, {len(rows) - len(todo) if not MAX_ROWS else len(done)} already handled, '
          f'{len(todo)} to do{" (dry run)" if DRY_RUN else ""}.')
    counts, failures_in_a_row = {}, 0
    for index, row in enumerate(todo, 1):
        driver, result = correct_with_recovery(driver, row)
        counts[result] = counts.get(result, 0) + 1
        failures_in_a_row = failures_in_a_row + 1 if result == 'failed' else 0
        if failures_in_a_row >= MAX_CONSECUTIVE_SKIPS:
            raise RuntimeError(f'{failures_in_a_row} failures in a row: TMDb or the browser is not in a normal state.')
        if index % 25 == 0:
            print(f'{index}/{len(todo)}: {counts}')
        time.sleep(pf.current_pause())
    print(f'Done: {counts}')
    return driver


def main():
    global DRY_RUN, MAX_ROWS
    parser = argparse.ArgumentParser(description='Correct the Places of Birth written with today\'s country.')
    parser.add_argument('--build', action='store_true', help='read-only: build the list from the logs and the database')
    parser.add_argument('--dry-run', action='store_true', help='pages checked, nothing saved')
    parser.add_argument('--max-rows', type=int, default=0, help='persons to handle, 0 for no limit (default: 0)')
    args = parser.parse_args()

    if args.build:
        build_list()
        return

    DRY_RUN, MAX_ROWS = args.dry_run, args.max_rows
    pf.DRY_RUN = DRY_RUN
    state = {'driver': None}

    def attempt():
        state['driver'] = replace_browser(state['driver'])
        state['driver'] = process_list(state['driver'])

    try:
        run_until_done(attempt, 'place-correction', throttled_types=(pf.TmdbThrottled,))
    finally:
        close_browser_when_done(state['driver'])


if __name__ == '__main__':
    main()
