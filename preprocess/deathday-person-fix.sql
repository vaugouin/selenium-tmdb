/*
Persons dead in Wikidata (P570, date of death) whose TMDb record has no death date at all.
CSV export of this query feeds the persons_deathday dataset of the notebook: FILL ONLY,
never replace a death date TMDb already has (2026-11-01).

Sizing (measure-deathday-imdb-gaps-20261101.txt at the repo root): 20 400 persons have a
day-precision P570 and no death on TMDb; 794 of them carry two different dates in Wikidata.

GUARDS
1. Day precision only (TIME_PRECISION = 11). TMDb's "Day of Death" is a full date; a year
   or a month from Wikidata would force us to invent the rest.
2. One date only. A person with two different non-deprecated P570 is skipped: Wikidata
   disagrees with itself and we cannot decide in its place (HAVING below).
3. Deprecated statements are ignored, as everywhere in this repo.
4. The QID must really be this person. TMDb sometimes carries the QID of a namesake: the
   first measure listed "Samuel Braun" (TMDb popularity 12.45) dead in 1668. Two checks:
   a. death year from 1890 on (cinema era) and not in the future;
   b. when TMDb has a birthday and Wikidata a day-precision P569, they must be the same
      day. A mismatch means the QID points to somebody else: nothing is written.
5. TMDb has no death information at all (DEATHDAY and DEATH_YEAR both empty).

Dates are compared as YEAR*10000 + MONTH*100 + DAY: T_WC_WIKIDATA_TIME_VALUE.DATE_START is
not filled for these rows (first measure, 2026-11-01). Column against column only, no CAST
in comparisons (see AGENTS.md, collation); the DATE_OF_DEATH string is output only.

Order: most popular first, so a short interactive run covers the most visible records.

⚠ THIS FILE IS EXECUTED EVERY MORNING by preprocess/selenium-tmdb.py through ONE
cursor.execute(). One statement only. See AGENTS.md, section "SQL files".
*/
SELECT
P.ID_PERSON AS ID_PERSON,
P.NAME AS NAME,
P.ID_WIKIDATA AS ID_WIKIDATA,
CONCAT(MIN(tv.YEAR_VALUE), '-', LPAD(MIN(tv.MONTH_VALUE), 2, '0'), '-', LPAD(MIN(tv.DAY_VALUE), 2, '0')) AS DATE_OF_DEATH,
P.BIRTHDAY AS TMDB_BIRTHDAY,
P.POPULARITY AS POPULARITY,
P.ADULT AS ADULT
FROM T_WC_WIKIDATA_STATEMENT s
INNER JOIN T_WC_WIKIDATA_TIME_VALUE tv ON tv.ID_STATEMENT = s.ID_STATEMENT
INNER JOIN T_WC_TMDB_PERSON P ON P.ID_WIKIDATA = s.ID_WIKIDATA
WHERE s.ID_PROPERTY = 'P570'
  AND (s.`RANK` IS NULL OR s.`RANK` <> 'deprecated')
  AND COALESCE(s.DELETED, 0) = 0
  AND tv.TIME_PRECISION = 11
  AND tv.YEAR_VALUE >= 1890 AND tv.MONTH_VALUE > 0 AND tv.DAY_VALUE > 0
  AND (tv.YEAR_VALUE * 10000 + tv.MONTH_VALUE * 100 + tv.DAY_VALUE)
      <= (YEAR(CURDATE()) * 10000 + MONTH(CURDATE()) * 100 + DAY(CURDATE()))
  AND P.DEATHDAY IS NULL AND P.DEATH_YEAR IS NULL
  AND COALESCE(P.DELETED, 0) = 0
  /* GUARD 4b: a TMDb birthday that contradicts Wikidata's P569 disqualifies the QID. */
  AND NOT EXISTS (
        SELECT 1
        FROM T_WC_WIKIDATA_STATEMENT sb
        INNER JOIN T_WC_WIKIDATA_TIME_VALUE tb ON tb.ID_STATEMENT = sb.ID_STATEMENT
        WHERE sb.ID_WIKIDATA = P.ID_WIKIDATA AND sb.ID_PROPERTY = 'P569'
          AND (sb.`RANK` IS NULL OR sb.`RANK` <> 'deprecated')
          AND tb.TIME_PRECISION = 11
          AND P.BIRTHDAY IS NOT NULL
          AND (tb.YEAR_VALUE * 10000 + tb.MONTH_VALUE * 100 + tb.DAY_VALUE)
              <> (YEAR(P.BIRTHDAY) * 10000 + MONTH(P.BIRTHDAY) * 100 + DAY(P.BIRTHDAY)) )
GROUP BY P.ID_PERSON, P.NAME, P.ID_WIKIDATA, P.BIRTHDAY, P.POPULARITY, P.ADULT
HAVING COUNT(DISTINCT (tv.YEAR_VALUE * 10000 + tv.MONTH_VALUE * 100 + tv.DAY_VALUE)) = 1
ORDER BY P.POPULARITY DESC, P.ID_PERSON ASC
