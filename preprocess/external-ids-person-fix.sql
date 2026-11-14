/*
External ids of TMDb persons that are empty on TMDb while Wikidata knows them:
FACEBOOK_ID (P2013, Facebook), INSTAGRAM_ID (P2003, Instagram), TWITTER_ID (P2002, X), TIKTOK_ID (P7085, TikTok), YOUTUBE_ID (P2397, YouTube channel), the IMDb id.
CSV export of this query feeds the external_ids tab of selenium-tmdb (2026-11-11), written
in the same visit as the wikidata_id.

ONE ROW PER RECORD, ONE COLUMN PER FIELD. An empty cell means "leave this field alone",
never "clear it". The robot checks the live page again before writing any field.

GUARDS
1. Identity of the QID, required for every field: Wikidata must point back at this TMDb
   record, P4985 (TMDb id) equal to ID_PERSON, or P345 (IMDb id) equal to the IMDb id TMDb
   holds. A namesake QID would otherwise put a stranger's accounts on the page.
   The IMDb id itself is filled only on the P4985 proof (the P345 proof needs it).
2. Social ids only on rows tmdb-crawler has read since its 1.0.12 (TIM_EXTERNAL_IDS not
   NULL) and only where TMDb has none ('' = read and empty, NULL = not read yet, unknown).
3. One clean value: best values only (IS_BEST_VALUE), not deprecated, not deleted, no end
   date (qualifier P582: an account closed or abandoned), exactly one distinct value. Two
   accounts on the same property leave the cell empty. DISTINCT follows the column
   collation (utf8mb4_unicode_ci), so one handle written in two cases counts once.
4. IMDb: empty on TMDb, well-formed, and not already held by
   another TMDb person (TMDb would point two records at one title).
5. Official account only (2026-11-14, after the first dry run): a social id is exported only
   when its Wikidata statement carries evidence, the account's numeric id (P6552 X, P12546
   Instagram, P11705 Facebook) or "verified account" (P1552 = Q28378282). A bare statement
   is not enough: the dry run proposed matt_damon_official (Matt Damon has no account),
   realltomholland on TikTok, PokemonVietnamJapan for Pokemon. Measured on records read by
   tmdb-crawler: X keeps most of its candidates (persons 3,415 of 3,989), Instagram about a
   quarter, Facebook and TikTok almost none (persons 40 of 2,570 and 4 of 311): those two are
   rarely qualified on Wikidata, and an empty cell is better than a fan page.
   YouTube (P2397, only on request) is left out of this guard: a channel id is its own
   numeric id.

The CONVERT(..., CHAR) COLLATE on the TMDb id follows primary-facts-person-fix.sql
(AGENTS.md, collation): P4985 values may be slugs, a bare numeric comparison fails.
Order: most popular first, so a short interactive run covers the most visible records.
*/
SELECT y.* FROM (
SELECT
x.ID_PERSON,
x.NAME,
x.ID_WIKIDATA,
x.IDENTITY,
x.FACEBOOK_ID,
x.INSTAGRAM_ID,
x.TWITTER_ID,
x.TIKTOK_ID,
x.YOUTUBE_ID,
CASE WHEN x.IDENTITY = 'P4985' AND x.IMDB_CANDIDATE IS NOT NULL
      AND NOT EXISTS ( SELECT 1 FROM T_WC_TMDB_PERSON d WHERE d.ID_IMDB = x.IMDB_CANDIDATE AND d.ID_PERSON <> x.ID_PERSON )
     THEN x.IMDB_CANDIDATE END AS ID_IMDB,
x.POPULARITY,
x.ADULT
FROM (
  SELECT
  T.ID_PERSON, T.NAME, T.ID_WIKIDATA, T.POPULARITY, T.ADULT,
  CASE WHEN EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_STATEMENT sv
                     INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE ev ON ev.ID_STATEMENT = sv.ID_STATEMENT
                     WHERE sv.ID_WIKIDATA = T.ID_WIKIDATA AND sv.ID_PROPERTY = 'P4985'
                       AND (sv.`RANK` IS NULL OR sv.`RANK` <> 'deprecated') AND COALESCE(sv.DELETED, 0) = 0
                       AND ev.VALUE_EXTERNAL_ID = CONVERT(T.ID_PERSON, CHAR) COLLATE utf8mb4_unicode_ci )
       THEN 'P4985'
       WHEN COALESCE(T.ID_IMDB, '') <> '' AND EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_STATEMENT si
                     INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE ei ON ei.ID_STATEMENT = si.ID_STATEMENT
                     WHERE si.ID_WIKIDATA = T.ID_WIKIDATA AND si.ID_PROPERTY = 'P345'
                       AND (si.`RANK` IS NULL OR si.`RANK` <> 'deprecated') AND COALESCE(si.DELETED, 0) = 0
                       AND ei.VALUE_EXTERNAL_ID = T.ID_IMDB )
       THEN 'P345' END AS IDENTITY,
  CASE WHEN T.TIM_EXTERNAL_IDS IS NOT NULL AND COALESCE(T.FACEBOOK_ID, '') = '' THEN
  ( SELECT CASE WHEN COUNT(DISTINCT ev.VALUE_EXTERNAL_ID) = 1 THEN MIN(ev.VALUE_EXTERNAL_ID) END
    FROM T_WC_WIKIDATA_STATEMENT s
    INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE ev ON ev.ID_STATEMENT = s.ID_STATEMENT
    WHERE s.ID_WIKIDATA = T.ID_WIKIDATA AND s.ID_PROPERTY = 'P2013'
      AND (s.`RANK` IS NULL OR s.`RANK` <> 'deprecated') AND COALESCE(s.DELETED, 0) = 0 AND COALESCE(s.IS_BEST_VALUE, 1) = 1
      AND NOT EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_STATEMENT_QUALIFIER q
                       WHERE q.ID_STATEMENT = s.ID_STATEMENT AND q.ID_QUALIFIER_PROPERTY = 'P582' )
      AND EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_STATEMENT_QUALIFIER qe
                   LEFT JOIN T_WC_WIKIDATA_QUALIFIER_ITEM_VALUE qv ON qv.ID_STATEMENT_QUALIFIER = qe.ID_STATEMENT_QUALIFIER
                   WHERE qe.ID_STATEMENT = s.ID_STATEMENT
                     AND ( qe.ID_QUALIFIER_PROPERTY IN ('P6552', 'P12546', 'P11705')
                        OR ( qe.ID_QUALIFIER_PROPERTY = 'P1552' AND qv.ID_ITEM = 'Q28378282' ) ) ) )
  END AS FACEBOOK_ID,
  CASE WHEN T.TIM_EXTERNAL_IDS IS NOT NULL AND COALESCE(T.INSTAGRAM_ID, '') = '' THEN
  ( SELECT CASE WHEN COUNT(DISTINCT ev.VALUE_EXTERNAL_ID) = 1 THEN MIN(ev.VALUE_EXTERNAL_ID) END
    FROM T_WC_WIKIDATA_STATEMENT s
    INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE ev ON ev.ID_STATEMENT = s.ID_STATEMENT
    WHERE s.ID_WIKIDATA = T.ID_WIKIDATA AND s.ID_PROPERTY = 'P2003'
      AND (s.`RANK` IS NULL OR s.`RANK` <> 'deprecated') AND COALESCE(s.DELETED, 0) = 0 AND COALESCE(s.IS_BEST_VALUE, 1) = 1
      AND NOT EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_STATEMENT_QUALIFIER q
                       WHERE q.ID_STATEMENT = s.ID_STATEMENT AND q.ID_QUALIFIER_PROPERTY = 'P582' )
      AND EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_STATEMENT_QUALIFIER qe
                   LEFT JOIN T_WC_WIKIDATA_QUALIFIER_ITEM_VALUE qv ON qv.ID_STATEMENT_QUALIFIER = qe.ID_STATEMENT_QUALIFIER
                   WHERE qe.ID_STATEMENT = s.ID_STATEMENT
                     AND ( qe.ID_QUALIFIER_PROPERTY IN ('P6552', 'P12546', 'P11705')
                        OR ( qe.ID_QUALIFIER_PROPERTY = 'P1552' AND qv.ID_ITEM = 'Q28378282' ) ) ) )
  END AS INSTAGRAM_ID,
  CASE WHEN T.TIM_EXTERNAL_IDS IS NOT NULL AND COALESCE(T.TWITTER_ID, '') = '' THEN
  ( SELECT CASE WHEN COUNT(DISTINCT ev.VALUE_EXTERNAL_ID) = 1 THEN MIN(ev.VALUE_EXTERNAL_ID) END
    FROM T_WC_WIKIDATA_STATEMENT s
    INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE ev ON ev.ID_STATEMENT = s.ID_STATEMENT
    WHERE s.ID_WIKIDATA = T.ID_WIKIDATA AND s.ID_PROPERTY = 'P2002'
      AND (s.`RANK` IS NULL OR s.`RANK` <> 'deprecated') AND COALESCE(s.DELETED, 0) = 0 AND COALESCE(s.IS_BEST_VALUE, 1) = 1
      AND NOT EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_STATEMENT_QUALIFIER q
                       WHERE q.ID_STATEMENT = s.ID_STATEMENT AND q.ID_QUALIFIER_PROPERTY = 'P582' )
      AND EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_STATEMENT_QUALIFIER qe
                   LEFT JOIN T_WC_WIKIDATA_QUALIFIER_ITEM_VALUE qv ON qv.ID_STATEMENT_QUALIFIER = qe.ID_STATEMENT_QUALIFIER
                   WHERE qe.ID_STATEMENT = s.ID_STATEMENT
                     AND ( qe.ID_QUALIFIER_PROPERTY IN ('P6552', 'P12546', 'P11705')
                        OR ( qe.ID_QUALIFIER_PROPERTY = 'P1552' AND qv.ID_ITEM = 'Q28378282' ) ) ) )
  END AS TWITTER_ID,
  CASE WHEN T.TIM_EXTERNAL_IDS IS NOT NULL AND COALESCE(T.TIKTOK_ID, '') = '' THEN
  ( SELECT CASE WHEN COUNT(DISTINCT ev.VALUE_EXTERNAL_ID) = 1 THEN MIN(ev.VALUE_EXTERNAL_ID) END
    FROM T_WC_WIKIDATA_STATEMENT s
    INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE ev ON ev.ID_STATEMENT = s.ID_STATEMENT
    WHERE s.ID_WIKIDATA = T.ID_WIKIDATA AND s.ID_PROPERTY = 'P7085'
      AND (s.`RANK` IS NULL OR s.`RANK` <> 'deprecated') AND COALESCE(s.DELETED, 0) = 0 AND COALESCE(s.IS_BEST_VALUE, 1) = 1
      AND NOT EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_STATEMENT_QUALIFIER q
                       WHERE q.ID_STATEMENT = s.ID_STATEMENT AND q.ID_QUALIFIER_PROPERTY = 'P582' )
      AND EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_STATEMENT_QUALIFIER qe
                   LEFT JOIN T_WC_WIKIDATA_QUALIFIER_ITEM_VALUE qv ON qv.ID_STATEMENT_QUALIFIER = qe.ID_STATEMENT_QUALIFIER
                   WHERE qe.ID_STATEMENT = s.ID_STATEMENT
                     AND ( qe.ID_QUALIFIER_PROPERTY IN ('P6552', 'P12546', 'P11705')
                        OR ( qe.ID_QUALIFIER_PROPERTY = 'P1552' AND qv.ID_ITEM = 'Q28378282' ) ) ) )
  END AS TIKTOK_ID,
  CASE WHEN T.TIM_EXTERNAL_IDS IS NOT NULL AND COALESCE(T.YOUTUBE_ID, '') = '' THEN
  ( SELECT CASE WHEN COUNT(DISTINCT ev.VALUE_EXTERNAL_ID) = 1 THEN MIN(ev.VALUE_EXTERNAL_ID) END
    FROM T_WC_WIKIDATA_STATEMENT s
    INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE ev ON ev.ID_STATEMENT = s.ID_STATEMENT
    WHERE s.ID_WIKIDATA = T.ID_WIKIDATA AND s.ID_PROPERTY = 'P2397'
      AND (s.`RANK` IS NULL OR s.`RANK` <> 'deprecated') AND COALESCE(s.DELETED, 0) = 0 AND COALESCE(s.IS_BEST_VALUE, 1) = 1
      AND NOT EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_STATEMENT_QUALIFIER q
                       WHERE q.ID_STATEMENT = s.ID_STATEMENT AND q.ID_QUALIFIER_PROPERTY = 'P582' ) )
  END AS YOUTUBE_ID,
  CASE WHEN COALESCE(T.ID_IMDB, '') = '' THEN
  ( SELECT CASE WHEN COUNT(DISTINCT ev.VALUE_EXTERNAL_ID) = 1 THEN MIN(ev.VALUE_EXTERNAL_ID) END
    FROM T_WC_WIKIDATA_STATEMENT s
    INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE ev ON ev.ID_STATEMENT = s.ID_STATEMENT
    WHERE s.ID_WIKIDATA = T.ID_WIKIDATA AND s.ID_PROPERTY = 'P345'
      AND (s.`RANK` IS NULL OR s.`RANK` <> 'deprecated') AND COALESCE(s.DELETED, 0) = 0 AND COALESCE(s.IS_BEST_VALUE, 1) = 1
      AND NOT EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_STATEMENT_QUALIFIER q
                       WHERE q.ID_STATEMENT = s.ID_STATEMENT AND q.ID_QUALIFIER_PROPERTY = 'P582' )
      AND ev.VALUE_EXTERNAL_ID REGEXP '^nm[0-9]+$' )
  END AS IMDB_CANDIDATE
  FROM T_WC_TMDB_PERSON T
  WHERE T.ID_WIKIDATA LIKE 'Q%'
    AND COALESCE(T.DELETED, 0) = 0
) x
WHERE x.IDENTITY IS NOT NULL
) y
/* Filtered on the final columns: a candidate dropped by guard 4 must not leave an empty row. */
WHERE y.FACEBOOK_ID IS NOT NULL
   OR y.INSTAGRAM_ID IS NOT NULL
   OR y.TWITTER_ID IS NOT NULL
   OR y.TIKTOK_ID IS NOT NULL
   OR y.YOUTUBE_ID IS NOT NULL
   OR y.ID_IMDB IS NOT NULL
ORDER BY y.POPULARITY DESC, y.ID_PERSON ASC
