/*
measure-deathday-imdb-gaps.sql : size two candidate datasets before building them (2026-11-01).

NOT EXECUTED BY THE DAILY EXPORT: this file sits at the repo root on purpose (preprocess/ is
globbed every morning, one statement per file). Read-only, run through the agent gate:
  ssh vps-agent run selenium-tmdb/measure-deathday-imdb-gaps.sql

A. Deaths: TMDb persons with a valid QID and no DEATHDAY, while Wikidata has a non-deprecated
   P570 (date of death). Split by Wikidata precision (11 = day, 10 = month, 9 = year): only a
   day-precision date can fill TMDb's "Day of Death" without inventing a day.
   Persons with two different day-precision P570 are counted apart: Wikidata disagrees with
   itself, so nothing would be written.
B. IMDb IDs: TMDb persons and movies with a valid QID and no IMDb ID, while Wikidata has a
   non-deprecated P345 of the right shape (nm... for persons, tt... for movies).
C. Death-source health: how many TMDb persons who ARE dead on TMDb have no P570 in V2,
   to judge the warning of wikidata-crawler/doc/sql/wikidata-v1-v2-followup.sql (36 % of V1
   death dates without P570 in V2).

Joins run from the Wikidata side (P570 / P345 statements, indexed by ID_PROPERTY) to the TMDb
side (ID_WIKIDATA indexed). Column against column only, no CAST (see AGENTS.md, collation).
*/

SELECT '=== A1. Deaths missing on TMDb, by Wikidata precision ===' AS section;

SELECT tv.TIME_PRECISION, COUNT(DISTINCT P.ID_PERSON) AS persons
FROM T_WC_WIKIDATA_STATEMENT s
INNER JOIN T_WC_WIKIDATA_TIME_VALUE tv ON tv.ID_STATEMENT = s.ID_STATEMENT
INNER JOIN T_WC_TMDB_PERSON P ON P.ID_WIKIDATA = s.ID_WIKIDATA
WHERE s.ID_PROPERTY = 'P570'
  AND (s.`RANK` IS NULL OR s.`RANK` <> 'deprecated')
  AND COALESCE(s.DELETED, 0) = 0
  AND P.DEATHDAY IS NULL AND P.DEATH_YEAR IS NULL
  AND COALESCE(P.DELETED, 0) = 0
GROUP BY tv.TIME_PRECISION
ORDER BY tv.TIME_PRECISION DESC;

SELECT '=== A2. Day precision: writable vs self-contradicting in Wikidata ===' AS section;

SELECT CASE WHEN n_dates = 1 THEN 'one date (writable)' ELSE 'several dates (skip)' END AS kind,
       COUNT(*) AS persons,
       SUM(ADULT = 0) AS non_adult,
       SUM(POPULARITY >= 1) AS popularity_ge_1
FROM (
  SELECT P.ID_PERSON, P.ADULT, P.POPULARITY, COUNT(DISTINCT tv.DATE_START) AS n_dates
  FROM T_WC_WIKIDATA_STATEMENT s
  INNER JOIN T_WC_WIKIDATA_TIME_VALUE tv ON tv.ID_STATEMENT = s.ID_STATEMENT
  INNER JOIN T_WC_TMDB_PERSON P ON P.ID_WIKIDATA = s.ID_WIKIDATA
  WHERE s.ID_PROPERTY = 'P570'
    AND (s.`RANK` IS NULL OR s.`RANK` <> 'deprecated')
    AND COALESCE(s.DELETED, 0) = 0
    AND tv.TIME_PRECISION = 11 AND tv.DATE_START IS NOT NULL
    AND P.DEATHDAY IS NULL AND P.DEATH_YEAR IS NULL
    AND COALESCE(P.DELETED, 0) = 0
  GROUP BY P.ID_PERSON, P.ADULT, P.POPULARITY
) t
GROUP BY kind;

SELECT '=== A3. Writable deaths, 30 most popular (sanity sample) ===' AS section;

SELECT P.ID_PERSON, P.NAME, P.ID_WIKIDATA, P.BIRTHDAY, MIN(tv.DATE_START) AS WIKIDATA_DEATH,
       ROUND(P.POPULARITY, 2) AS POPULARITY
FROM T_WC_WIKIDATA_STATEMENT s
INNER JOIN T_WC_WIKIDATA_TIME_VALUE tv ON tv.ID_STATEMENT = s.ID_STATEMENT
INNER JOIN T_WC_TMDB_PERSON P ON P.ID_WIKIDATA = s.ID_WIKIDATA
WHERE s.ID_PROPERTY = 'P570'
  AND (s.`RANK` IS NULL OR s.`RANK` <> 'deprecated')
  AND COALESCE(s.DELETED, 0) = 0
  AND tv.TIME_PRECISION = 11 AND tv.DATE_START IS NOT NULL
  AND P.DEATHDAY IS NULL AND P.DEATH_YEAR IS NULL
  AND COALESCE(P.DELETED, 0) = 0 AND P.ADULT = 0
GROUP BY P.ID_PERSON, P.NAME, P.ID_WIKIDATA, P.BIRTHDAY, P.POPULARITY
HAVING COUNT(DISTINCT tv.DATE_START) = 1
ORDER BY P.POPULARITY DESC
LIMIT 30;

SELECT '=== A4. Writable deaths by death year (recent deaths first) ===' AS section;

SELECT CASE WHEN YEAR(d) >= 2025 THEN '2025+' WHEN YEAR(d) >= 2020 THEN '2020-2024'
            WHEN YEAR(d) >= 2000 THEN '2000-2019' ELSE 'before 2000' END AS died,
       COUNT(*) AS persons
FROM (
  SELECT P.ID_PERSON, MIN(tv.DATE_START) AS d
  FROM T_WC_WIKIDATA_STATEMENT s
  INNER JOIN T_WC_WIKIDATA_TIME_VALUE tv ON tv.ID_STATEMENT = s.ID_STATEMENT
  INNER JOIN T_WC_TMDB_PERSON P ON P.ID_WIKIDATA = s.ID_WIKIDATA
  WHERE s.ID_PROPERTY = 'P570'
    AND (s.`RANK` IS NULL OR s.`RANK` <> 'deprecated')
    AND COALESCE(s.DELETED, 0) = 0
    AND tv.TIME_PRECISION = 11 AND tv.DATE_START IS NOT NULL
    AND P.DEATHDAY IS NULL AND P.DEATH_YEAR IS NULL
    AND COALESCE(P.DELETED, 0) = 0
  GROUP BY P.ID_PERSON
  HAVING COUNT(DISTINCT tv.DATE_START) = 1
) t
GROUP BY died
ORDER BY died DESC;

SELECT '=== B1. Persons: IMDb ID missing on TMDb, known to Wikidata ===' AS section;

SELECT COUNT(DISTINCT P.ID_PERSON) AS persons, COUNT(DISTINCT CASE WHEN P.ADULT = 0 THEN P.ID_PERSON END) AS non_adult
FROM T_WC_WIKIDATA_STATEMENT s
INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE e ON e.ID_STATEMENT = s.ID_STATEMENT
INNER JOIN T_WC_TMDB_PERSON P ON P.ID_WIKIDATA = s.ID_WIKIDATA
WHERE s.ID_PROPERTY = 'P345'
  AND (s.`RANK` IS NULL OR s.`RANK` <> 'deprecated')
  AND COALESCE(s.DELETED, 0) = 0
  AND e.VALUE_EXTERNAL_ID REGEXP '^nm[0-9]{7,8}$'
  AND (P.ID_IMDB IS NULL OR P.ID_IMDB = '')
  AND COALESCE(P.DELETED, 0) = 0;

SELECT '=== B2. Movies: IMDb ID missing on TMDb, known to Wikidata ===' AS section;

SELECT COUNT(DISTINCT M.ID_MOVIE) AS movies
FROM T_WC_WIKIDATA_STATEMENT s
INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE e ON e.ID_STATEMENT = s.ID_STATEMENT
INNER JOIN T_WC_TMDB_MOVIE M ON M.ID_WIKIDATA = s.ID_WIKIDATA
WHERE s.ID_PROPERTY = 'P345'
  AND (s.`RANK` IS NULL OR s.`RANK` <> 'deprecated')
  AND COALESCE(s.DELETED, 0) = 0
  AND e.VALUE_EXTERNAL_ID REGEXP '^tt[0-9]{7,8}$'
  AND (M.ID_IMDB IS NULL OR M.ID_IMDB = '')
  AND COALESCE(M.DELETED, 0) = 0;

SELECT '=== C. Death-source health: dead on TMDb, with or without P570 in V2 ===' AS section;

SELECT CASE WHEN EXISTS (SELECT 1 FROM T_WC_WIKIDATA_STATEMENT s
                         WHERE s.ID_WIKIDATA = P.ID_WIKIDATA AND s.ID_PROPERTY = 'P570')
            THEN 'has P570' ELSE 'no P570' END AS v2,
       COUNT(*) AS persons
FROM T_WC_TMDB_PERSON P
WHERE P.DEATHDAY IS NOT NULL
  AND P.ID_WIKIDATA REGEXP '^Q[0-9]+$'
  AND COALESCE(P.DELETED, 0) = 0
GROUP BY v2;
