/*
TMDb persons whose primary facts (Day of Death, Birthday, Gender, Place of Birth) are empty
on TMDb while Wikidata knows them. CSV export of this query feeds the persons_primary_facts
dataset of selenium-tmdb-deathday.ipynb (2026-11-02; replaces deathday-person-fix.sql, which
fed the first death-date run of the same day).

ONE ROW PER PERSON, ONE COLUMN PER FIELD. An empty cell means "leave this field alone",
never "clear it": a column is filled only when Wikidata has one clean value AND the field is
empty in our TMDb copy. The notebook checks the live page again before writing any field.

GUARDS
1. Identity of the QID, required for every field. TMDb sometimes carries the QID of a
   namesake (first death measure: "Samuel Braun" dead in 1668; Joan Gregson, a Canadian
   actress, with a Paris birthplace). A row is exported only when Wikidata points back at
   this TMDb record: P4985 (TMDB person ID) equals ID_PERSON, or P345 (IMDb ID) equals the
   IMDb ID TMDb holds.
2. Contradiction: when TMDb already has a birthday (or a death date) and Wikidata has a
   different day-precision one, the QID is suspect and the whole row is dropped.
3. Dates: day precision (TIME_PRECISION = 11), Gregorian calendar (Julian dates would be
   off by ten days or more), one distinct date among non-deprecated statements, year from
   1800 on, not in the future, birth before death.
4. Gender: P21 with one distinct value among female (TMDb 1), male (2), non-binary (3).
   Any other value, or two values, leaves the cell empty. Written only when TMDb has 0.
5. Place of birth: P19 with one distinct place, which has an English label and one
   country (P17), and is not the country itself. Written as TMDb writes it:
   "City, Country", with the state or constituent country for USA, UK, Canada and
   Australia ("Los Angeles, California, USA", "London, England, UK"), found one to three
   P131 levels up; in those four countries a place whose region is not found is left
   empty. Also left empty: a place that is a country, a dissolved country (P576, "Empire
   of Japan", "Ancient Rome"). Country names TMDb writes short: USA, UK, China,
   Netherlands. A label starting in lower case is a street or a district, not a town
   ("boulevard Saint-Martin"): left empty. Country (P17) and region (P131) read only the
   best values (IS_BEST_VALUE), so a historical one does not win: the first test gave
   "Portland, Massachusetts" for Portland, Maine (part of Massachusetts until 1820).
   PLACE_OF_BIRTH_QID is kept in the CSV for review.
5b. Place of birth, country of the time (2026-11-14). TMDb's rule (People Bible): "the place
   of birth should reflect the names and political divisions used at the time of birth",
   today's name in brackets. Until 2026-11-13 this export wrote today's country ("Brno,
   Czech Republic" for a birth in Czechoslovakia), reported by a TMDb contributor. The
   country of the time comes from T_WC_COUNTRY (ID_WIKIDATA, DAT_START) and
   T_WC_COUNTRY_SUCCESSION (tmdb-person-preprocess, migrations/add_defunct_countries.py):
   - the first succession row of today's country covering the birth date gives it, region
     rows first (P131 of the place, one to three levels up, region not found: nothing), a
     row without country means "not known": nothing,
   - no row: today's country, unless it did not exist yet (DAT_START after the birth),
   - no birth date: today's country only when its history stays before 1950.
   Same country: written as before. Another, defunct one: "City, Czechoslovakia [now Czech
   Republic]", else "City, Czechoslovakia", only when that exact text is already the Place
   of Birth of 3 persons on TMDb. The database does not know renamed cities ("Saint
   Petersburg, USSR" would be wrong for Leningrad): a form contributors already use is the
   guard. Otherwise nothing is written. PLACE_COUNTRY_AT_BIRTH is kept in the CSV for review
   ('SAME' = a country the tables do not know, '-' = not known).
6. Deprecated or deleted statements are ignored, as everywhere in this repo.

Dates are compared as YEAR*10000 + MONTH*100 + DAY: DATE_START is not filled for these rows.
Guard 1 compares P4985 as a string, CONVERT(ID_PERSON, CHAR) COLLATE utf8mb4_unicode_ci on the
TMDb side (AGENTS.md, collation): a bare numeric comparison failed on P4985 values that are
slugs ('2371017-arianna-martinez', ERROR 1292, first test 2026-11-02). The CONCAT strings are
output only.

Order: most popular first, so a short interactive run covers the most visible records.

⚠ THIS FILE IS EXECUTED EVERY MORNING by preprocess/selenium-tmdb.py through ONE
cursor.execute(). One statement only. See AGENTS.md, section "SQL files".
*/
SELECT x.* FROM (
SELECT
y.ID_PERSON AS ID_PERSON,
y.NAME AS NAME,
y.ID_WIKIDATA AS ID_WIKIDATA,
y.IDENTITY AS IDENTITY,
y.DATE_OF_DEATH AS DATE_OF_DEATH,
y.DATE_OF_BIRTH AS DATE_OF_BIRTH,
y.GENDER AS GENDER,
CASE WHEN y.PLACE_TODAY IS NULL THEN NULL
     /* GUARD 5b: same country at the birth, or a country the tables do not know */
     WHEN y.AT_BIRTH = 'SAME' OR y.AT_BIRTH = y.COUNTRY_CODE THEN y.PLACE_TODAY
     /* a defunct country: a form already used on TMDb, today's name in brackets first */
     WHEN hc.PLACE_NAME_EN IS NOT NULL AND y.PL_LABEL IS NOT NULL THEN
       CASE WHEN ( SELECT COUNT(*) FROM T_WC_TMDB_PERSON u
                   WHERE u.PLACE_OF_BIRTH = CONCAT(y.PL_LABEL, ', ', hc.PLACE_NAME_EN, ' [now ', y.COUNTRY_NAME_NOW, ']') ) >= 3
            THEN CONCAT(y.PL_LABEL, ', ', hc.PLACE_NAME_EN, ' [now ', y.COUNTRY_NAME_NOW, ']')
            WHEN ( SELECT COUNT(*) FROM T_WC_TMDB_PERSON u
                   WHERE u.PLACE_OF_BIRTH = CONCAT(y.PL_LABEL, ', ', hc.PLACE_NAME_EN) ) >= 3
            THEN CONCAT(y.PL_LABEL, ', ', hc.PLACE_NAME_EN) END
END AS PLACE_OF_BIRTH,
y.PLACE_QID AS PLACE_OF_BIRTH_QID,
y.AT_BIRTH AS PLACE_COUNTRY_AT_BIRTH,
y.POPULARITY AS POPULARITY,
y.ADULT AS ADULT
FROM (
SELECT
f.ID_PERSON, f.NAME, f.ID_WIKIDATA, f.IDENTITY, f.PLACE_QID, f.POPULARITY, f.ADULT,
CASE WHEN f.DEATH_YMD IS NOT NULL AND (f.BIRTH_YMD IS NULL OR f.BIRTH_YMD < f.DEATH_YMD)
          AND (f.TMDB_BIRTH_YMD IS NULL OR f.TMDB_BIRTH_YMD < f.DEATH_YMD)
     THEN CONCAT(f.DEATH_YMD DIV 10000, '-', LPAD(f.DEATH_YMD DIV 100 MOD 100, 2, '0'), '-', LPAD(f.DEATH_YMD MOD 100, 2, '0'))
END AS DATE_OF_DEATH,
CASE WHEN f.BIRTH_YMD IS NOT NULL AND (f.DEATH_YMD IS NULL OR f.BIRTH_YMD < f.DEATH_YMD)
          AND (f.TMDB_DEATH_YMD IS NULL OR f.BIRTH_YMD < f.TMDB_DEATH_YMD)
     THEN CONCAT(f.BIRTH_YMD DIV 10000, '-', LPAD(f.BIRTH_YMD DIV 100 MOD 100, 2, '0'), '-', LPAD(f.BIRTH_YMD MOD 100, 2, '0'))
END AS DATE_OF_BIRTH,
CASE f.GENDER_QID WHEN 'Q6581072' THEN 1 WHEN 'Q6581097' THEN 2 WHEN 'Q48270' THEN 3 END AS GENDER,
/* GUARD 5: no string at all rather than a doubtful one. The place as written today. */
CASE WHEN f.PLACE_QID IS NOT NULL AND pl.LABEL_EN IS NOT NULL AND pl.LABEL_EN <> ''
          AND LEFT(pl.LABEL_EN, 1) COLLATE utf8mb4_bin <> LOWER(LEFT(pl.LABEL_EN, 1)) COLLATE utf8mb4_bin
          AND f.COUNTRY_QID IS NOT NULL AND f.COUNTRY_QID <> f.PLACE_QID
          AND co.LABEL_EN IS NOT NULL AND co.LABEL_EN <> ''
          AND f.PLACE_IS_COUNTRY = 0 AND f.COUNTRY_DISSOLVED = 0
          AND (f.REGION_QID IS NULL OR f.REGION_QID <> f.PLACE_QID)
          /* In the four countries written with a region, the region must be found
             (or be the place itself: "California, USA", "Washington, D.C., USA"). */
          AND (f.COUNTRY_QID NOT IN ('Q30', 'Q145', 'Q16', 'Q408')
               OR f.REGION_QID IS NOT NULL OR f.PLACE_IS_REGION = 1)
     THEN CONCAT_WS(', ', pl.LABEL_EN, rg.LABEL_EN,
                    CASE f.COUNTRY_QID WHEN 'Q30' THEN 'USA' WHEN 'Q145' THEN 'UK'
                                       WHEN 'Q148' THEN 'China' WHEN 'Q29999' THEN 'Netherlands'
                                       ELSE co.LABEL_EN END)
END AS PLACE_TODAY,
pl.LABEL_EN AS PL_LABEL,
cc.COUNTRY_CODE AS COUNTRY_CODE,
COALESCE(cc.PLACE_NAME_EN, co.LABEL_EN) AS COUNTRY_NAME_NOW,
/* GUARD 5b: the country at the birth. 'SAME' = a country T_WC_COUNTRY does not know,
   '-' = not known (write nothing). */
CASE WHEN f.PLACE_QID IS NULL THEN NULL
     WHEN cc.COUNTRY_CODE IS NULL THEN 'SAME'
     WHEN COALESCE(f.TMDB_BIRTH_YMD, f.BIRTH_YMD) IS NULL THEN
       CASE WHEN (cc.DAT_START IS NULL OR cc.DAT_START < '1950-01-01')
                 AND NOT EXISTS ( SELECT 1 FROM T_WC_COUNTRY_SUCCESSION s0
                                  WHERE s0.COUNTRY_CODE = cc.COUNTRY_CODE AND COALESCE(s0.DELETED, 0) = 0
                                    AND s0.DAT_END >= '1950-01-01' )
            THEN cc.COUNTRY_CODE ELSE '-' END
     ELSE COALESCE(
       ( SELECT CASE WHEN sc.REGION_QIDS IS NOT NULL AND COALESCE(f.REGION_CHAIN, '') = '' THEN '-'
                     ELSE COALESCE(sc.COUNTRY_CODE_AT_BIRTH, '-') END
         FROM T_WC_COUNTRY_SUCCESSION sc
         WHERE sc.COUNTRY_CODE = cc.COUNTRY_CODE AND COALESCE(sc.DELETED, 0) = 0
           AND COALESCE(f.TMDB_BIRTH_YMD, f.BIRTH_YMD)
               BETWEEN YEAR(sc.DAT_START) * 10000 + MONTH(sc.DAT_START) * 100 + DAY(sc.DAT_START)
                   AND YEAR(sc.DAT_END) * 10000 + MONTH(sc.DAT_END) * 100 + DAY(sc.DAT_END)
           AND ( sc.REGION_QIDS IS NULL OR COALESCE(f.REGION_CHAIN, '') = ''
                 OR CONCAT(',', f.REGION_CHAIN, ',') REGEXP CONCAT(',(', REPLACE(sc.REGION_QIDS, ',', '|'), '),') )
         ORDER BY sc.DISPLAY_ORDER
         LIMIT 1 ),
       CASE WHEN cc.DAT_START IS NULL
                 OR YEAR(cc.DAT_START) * 10000 + MONTH(cc.DAT_START) * 100 + DAY(cc.DAT_START)
                    <= COALESCE(f.TMDB_BIRTH_YMD, f.BIRTH_YMD)
            THEN cc.COUNTRY_CODE ELSE '-' END )
END AS AT_BIRTH
FROM (
  SELECT g.*,
  /* State, province or constituent country of the place, one to three P131 levels up
     (city, county, state), for the four countries where TMDb writes it. */
  CASE WHEN g.COUNTRY_QID IN ('Q30', 'Q145', 'Q16', 'Q408') AND g.PLACE_IS_REGION = 0 THEN COALESCE(
    ( SELECT av.ID_ITEM
      FROM T_WC_WIKIDATA_STATEMENT a
      INNER JOIN T_WC_WIKIDATA_ITEM_VALUE av ON av.ID_STATEMENT = a.ID_STATEMENT
      WHERE a.ID_WIKIDATA = g.PLACE_QID AND a.ID_PROPERTY = 'P131'
        AND (a.`RANK` IS NULL OR a.`RANK` <> 'deprecated') AND COALESCE(a.DELETED, 0) = 0 AND COALESCE(a.IS_BEST_VALUE, 1) = 1
        AND ( av.ID_ITEM IN ('Q21', 'Q22', 'Q25', 'Q26', 'Q61')
              OR EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_STATEMENT c
                          INNER JOIN T_WC_WIKIDATA_ITEM_VALUE cv ON cv.ID_STATEMENT = c.ID_STATEMENT
                          WHERE c.ID_WIKIDATA = av.ID_ITEM AND c.ID_PROPERTY = 'P31'
                            AND cv.ID_ITEM IN ('Q35657', 'Q11828004', 'Q9357527', 'Q5852411', 'Q14192252') ) )
      ORDER BY (a.`RANK` = 'preferred') DESC, a.ID_STATEMENT
      LIMIT 1 ),
    ( SELECT bv.ID_ITEM
      FROM T_WC_WIKIDATA_STATEMENT a
      INNER JOIN T_WC_WIKIDATA_ITEM_VALUE av ON av.ID_STATEMENT = a.ID_STATEMENT
      INNER JOIN T_WC_WIKIDATA_STATEMENT b ON b.ID_WIKIDATA = av.ID_ITEM AND b.ID_PROPERTY = 'P131'
      INNER JOIN T_WC_WIKIDATA_ITEM_VALUE bv ON bv.ID_STATEMENT = b.ID_STATEMENT
      WHERE a.ID_WIKIDATA = g.PLACE_QID AND a.ID_PROPERTY = 'P131'
        AND (a.`RANK` IS NULL OR a.`RANK` <> 'deprecated') AND COALESCE(a.DELETED, 0) = 0 AND COALESCE(a.IS_BEST_VALUE, 1) = 1
        AND (b.`RANK` IS NULL OR b.`RANK` <> 'deprecated') AND COALESCE(b.DELETED, 0) = 0 AND COALESCE(b.IS_BEST_VALUE, 1) = 1
        AND ( bv.ID_ITEM IN ('Q21', 'Q22', 'Q25', 'Q26', 'Q61')
              OR EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_STATEMENT c
                          INNER JOIN T_WC_WIKIDATA_ITEM_VALUE cv ON cv.ID_STATEMENT = c.ID_STATEMENT
                          WHERE c.ID_WIKIDATA = bv.ID_ITEM AND c.ID_PROPERTY = 'P31'
                            AND cv.ID_ITEM IN ('Q35657', 'Q11828004', 'Q9357527', 'Q5852411', 'Q14192252') ) )
      ORDER BY (a.`RANK` = 'preferred') DESC, a.ID_STATEMENT, b.ID_STATEMENT
      LIMIT 1 ),
    ( SELECT dv.ID_ITEM
      FROM T_WC_WIKIDATA_STATEMENT a
      INNER JOIN T_WC_WIKIDATA_ITEM_VALUE av ON av.ID_STATEMENT = a.ID_STATEMENT
      INNER JOIN T_WC_WIKIDATA_STATEMENT b ON b.ID_WIKIDATA = av.ID_ITEM AND b.ID_PROPERTY = 'P131'
      INNER JOIN T_WC_WIKIDATA_ITEM_VALUE bv ON bv.ID_STATEMENT = b.ID_STATEMENT
      INNER JOIN T_WC_WIKIDATA_STATEMENT d ON d.ID_WIKIDATA = bv.ID_ITEM AND d.ID_PROPERTY = 'P131'
      INNER JOIN T_WC_WIKIDATA_ITEM_VALUE dv ON dv.ID_STATEMENT = d.ID_STATEMENT
      WHERE a.ID_WIKIDATA = g.PLACE_QID AND a.ID_PROPERTY = 'P131'
        AND (a.`RANK` IS NULL OR a.`RANK` <> 'deprecated') AND COALESCE(a.DELETED, 0) = 0 AND COALESCE(a.IS_BEST_VALUE, 1) = 1
        AND (b.`RANK` IS NULL OR b.`RANK` <> 'deprecated') AND COALESCE(b.DELETED, 0) = 0 AND COALESCE(b.IS_BEST_VALUE, 1) = 1
        AND (d.`RANK` IS NULL OR d.`RANK` <> 'deprecated') AND COALESCE(d.DELETED, 0) = 0 AND COALESCE(d.IS_BEST_VALUE, 1) = 1
        AND ( dv.ID_ITEM IN ('Q21', 'Q22', 'Q25', 'Q26', 'Q61')
              OR EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_STATEMENT c
                          INNER JOIN T_WC_WIKIDATA_ITEM_VALUE cv ON cv.ID_STATEMENT = c.ID_STATEMENT
                          WHERE c.ID_WIKIDATA = dv.ID_ITEM AND c.ID_PROPERTY = 'P31'
                            AND cv.ID_ITEM IN ('Q35657', 'Q11828004', 'Q9357527', 'Q5852411', 'Q14192252') ) )
      ORDER BY (a.`RANK` = 'preferred') DESC, a.ID_STATEMENT, b.ID_STATEMENT, d.ID_STATEMENT
      LIMIT 1 ) ) END AS REGION_QID,
  /* Every P131 of the place, one to three levels up, for the countries whose succession
     rows depend on the region (Germany, Italy, Russia): read by GUARD 5b. */
  CASE WHEN EXISTS ( SELECT 1 FROM T_WC_COUNTRY c1
                     INNER JOIN T_WC_COUNTRY_SUCCESSION s1 ON s1.COUNTRY_CODE = c1.COUNTRY_CODE
                     WHERE c1.ID_WIKIDATA = g.COUNTRY_QID AND c1.IS_DEFUNCT = 0 AND s1.REGION_QIDS IS NOT NULL )
       THEN CONCAT_WS(',',
         ( SELECT GROUP_CONCAT(av.ID_ITEM)
           FROM T_WC_WIKIDATA_STATEMENT a
           INNER JOIN T_WC_WIKIDATA_ITEM_VALUE av ON av.ID_STATEMENT = a.ID_STATEMENT
           WHERE a.ID_WIKIDATA = g.PLACE_QID AND a.ID_PROPERTY = 'P131'
             AND (a.`RANK` IS NULL OR a.`RANK` <> 'deprecated') AND COALESCE(a.DELETED, 0) = 0 ),
         ( SELECT GROUP_CONCAT(bv.ID_ITEM)
           FROM T_WC_WIKIDATA_STATEMENT a
           INNER JOIN T_WC_WIKIDATA_ITEM_VALUE av ON av.ID_STATEMENT = a.ID_STATEMENT
           INNER JOIN T_WC_WIKIDATA_STATEMENT b ON b.ID_WIKIDATA = av.ID_ITEM AND b.ID_PROPERTY = 'P131'
           INNER JOIN T_WC_WIKIDATA_ITEM_VALUE bv ON bv.ID_STATEMENT = b.ID_STATEMENT
           WHERE a.ID_WIKIDATA = g.PLACE_QID AND a.ID_PROPERTY = 'P131'
             AND (a.`RANK` IS NULL OR a.`RANK` <> 'deprecated') AND COALESCE(a.DELETED, 0) = 0
             AND (b.`RANK` IS NULL OR b.`RANK` <> 'deprecated') AND COALESCE(b.DELETED, 0) = 0 ),
         ( SELECT GROUP_CONCAT(dv.ID_ITEM)
           FROM T_WC_WIKIDATA_STATEMENT a
           INNER JOIN T_WC_WIKIDATA_ITEM_VALUE av ON av.ID_STATEMENT = a.ID_STATEMENT
           INNER JOIN T_WC_WIKIDATA_STATEMENT b ON b.ID_WIKIDATA = av.ID_ITEM AND b.ID_PROPERTY = 'P131'
           INNER JOIN T_WC_WIKIDATA_ITEM_VALUE bv ON bv.ID_STATEMENT = b.ID_STATEMENT
           INNER JOIN T_WC_WIKIDATA_STATEMENT d ON d.ID_WIKIDATA = bv.ID_ITEM AND d.ID_PROPERTY = 'P131'
           INNER JOIN T_WC_WIKIDATA_ITEM_VALUE dv ON dv.ID_STATEMENT = d.ID_STATEMENT
           WHERE a.ID_WIKIDATA = g.PLACE_QID AND a.ID_PROPERTY = 'P131'
             AND (a.`RANK` IS NULL OR a.`RANK` <> 'deprecated') AND COALESCE(a.DELETED, 0) = 0
             AND (b.`RANK` IS NULL OR b.`RANK` <> 'deprecated') AND COALESCE(b.DELETED, 0) = 0
             AND (d.`RANK` IS NULL OR d.`RANK` <> 'deprecated') AND COALESCE(d.DELETED, 0) = 0 ) )
  END AS REGION_CHAIN
  FROM (
    SELECT h.*,
    /* A dissolved country (P576) is history, not an address: "Tokyo City, Empire of Japan". */
    CASE WHEN EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_STATEMENT z
                       WHERE z.ID_WIKIDATA = h.COUNTRY_QID AND z.ID_PROPERTY = 'P576'
                         AND (z.`RANK` IS NULL OR z.`RANK` <> 'deprecated') ) THEN 1 ELSE 0 END AS COUNTRY_DISSOLVED
    FROM (
    SELECT e.*,
    /* Country of the place: one distinct P17. */
    ( SELECT CASE WHEN COUNT(DISTINCT kv.ID_ITEM) = 1 THEN MIN(kv.ID_ITEM) END
      FROM T_WC_WIKIDATA_STATEMENT k
      INNER JOIN T_WC_WIKIDATA_ITEM_VALUE kv ON kv.ID_STATEMENT = k.ID_STATEMENT
      WHERE k.ID_WIKIDATA = e.PLACE_QID AND k.ID_PROPERTY = 'P17'
        AND (k.`RANK` IS NULL OR k.`RANK` <> 'deprecated') AND COALESCE(k.DELETED, 0) = 0 AND COALESCE(k.IS_BEST_VALUE, 1) = 1 ) AS COUNTRY_QID
    , CASE WHEN ( e.PLACE_QID IN ('Q21', 'Q22', 'Q25', 'Q26', 'Q61')
              OR EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_STATEMENT c
                          INNER JOIN T_WC_WIKIDATA_ITEM_VALUE cv ON cv.ID_STATEMENT = c.ID_STATEMENT
                          WHERE c.ID_WIKIDATA = e.PLACE_QID AND c.ID_PROPERTY = 'P31'
                            AND cv.ID_ITEM IN ('Q35657', 'Q11828004', 'Q9357527', 'Q5852411', 'Q14192252') ) ) THEN 1 ELSE 0 END AS PLACE_IS_REGION
    , CASE WHEN EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_STATEMENT c
                         INNER JOIN T_WC_WIKIDATA_ITEM_VALUE cv ON cv.ID_STATEMENT = c.ID_STATEMENT
                         WHERE c.ID_WIKIDATA = e.PLACE_QID AND c.ID_PROPERTY = 'P31'
                           AND cv.ID_ITEM IN ('Q6256', 'Q3624078') ) THEN 1 ELSE 0 END AS PLACE_IS_COUNTRY
    FROM (
      SELECT
      P.ID_PERSON, P.NAME, P.ID_WIKIDATA, P.POPULARITY, P.ADULT,
      CASE WHEN EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_STATEMENT sv
                         INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE ev ON ev.ID_STATEMENT = sv.ID_STATEMENT
                         WHERE sv.ID_WIKIDATA = P.ID_WIKIDATA AND sv.ID_PROPERTY = 'P4985'
                           AND (sv.`RANK` IS NULL OR sv.`RANK` <> 'deprecated')
                           AND ev.VALUE_EXTERNAL_ID = CONVERT(P.ID_PERSON, CHAR) COLLATE utf8mb4_unicode_ci )
           THEN 'P4985' ELSE 'P345' END AS IDENTITY,
      CASE WHEN P.BIRTHDAY IS NULL THEN NULL
           ELSE YEAR(P.BIRTHDAY) * 10000 + MONTH(P.BIRTHDAY) * 100 + DAY(P.BIRTHDAY) END AS TMDB_BIRTH_YMD,
      CASE WHEN P.DEATHDAY IS NULL THEN NULL
           ELSE YEAR(P.DEATHDAY) * 10000 + MONTH(P.DEATHDAY) * 100 + DAY(P.DEATHDAY) END AS TMDB_DEATH_YMD,
      CASE WHEN P.DEATHDAY IS NULL AND P.DEATH_YEAR IS NULL THEN
        ( SELECT CASE WHEN COUNT(DISTINCT tv.YEAR_VALUE * 10000 + tv.MONTH_VALUE * 100 + tv.DAY_VALUE) = 1
                      THEN MIN(tv.YEAR_VALUE * 10000 + tv.MONTH_VALUE * 100 + tv.DAY_VALUE) END
          FROM T_WC_WIKIDATA_STATEMENT s
          INNER JOIN T_WC_WIKIDATA_TIME_VALUE tv ON tv.ID_STATEMENT = s.ID_STATEMENT
          WHERE s.ID_WIKIDATA = P.ID_WIKIDATA AND s.ID_PROPERTY = 'P570'
            AND (s.`RANK` IS NULL OR s.`RANK` <> 'deprecated') AND COALESCE(s.DELETED, 0) = 0
            AND tv.TIME_PRECISION = 11 AND tv.CALENDAR_MODEL LIKE '%Q1985727'
            AND tv.YEAR_VALUE >= 1800 AND tv.MONTH_VALUE > 0 AND tv.DAY_VALUE > 0
            AND (tv.YEAR_VALUE * 10000 + tv.MONTH_VALUE * 100 + tv.DAY_VALUE)
                <= (YEAR(CURDATE()) * 10000 + MONTH(CURDATE()) * 100 + DAY(CURDATE())) )
      END AS DEATH_YMD,
      CASE WHEN P.BIRTHDAY IS NULL AND P.BIRTH_YEAR IS NULL THEN
        ( SELECT CASE WHEN COUNT(DISTINCT tv.YEAR_VALUE * 10000 + tv.MONTH_VALUE * 100 + tv.DAY_VALUE) = 1
                      THEN MIN(tv.YEAR_VALUE * 10000 + tv.MONTH_VALUE * 100 + tv.DAY_VALUE) END
          FROM T_WC_WIKIDATA_STATEMENT s
          INNER JOIN T_WC_WIKIDATA_TIME_VALUE tv ON tv.ID_STATEMENT = s.ID_STATEMENT
          WHERE s.ID_WIKIDATA = P.ID_WIKIDATA AND s.ID_PROPERTY = 'P569'
            AND (s.`RANK` IS NULL OR s.`RANK` <> 'deprecated') AND COALESCE(s.DELETED, 0) = 0
            AND tv.TIME_PRECISION = 11 AND tv.CALENDAR_MODEL LIKE '%Q1985727'
            AND tv.YEAR_VALUE >= 1800 AND tv.MONTH_VALUE > 0 AND tv.DAY_VALUE > 0
            AND (tv.YEAR_VALUE * 10000 + tv.MONTH_VALUE * 100 + tv.DAY_VALUE)
                <= (YEAR(CURDATE()) * 10000 + MONTH(CURDATE()) * 100 + DAY(CURDATE())) )
      END AS BIRTH_YMD,
      CASE WHEN COALESCE(P.GENDER, 0) = 0 THEN
        ( SELECT CASE WHEN COUNT(DISTINCT gv.ID_ITEM) = 1 THEN MIN(gv.ID_ITEM) END
          FROM T_WC_WIKIDATA_STATEMENT s
          INNER JOIN T_WC_WIKIDATA_ITEM_VALUE gv ON gv.ID_STATEMENT = s.ID_STATEMENT
          WHERE s.ID_WIKIDATA = P.ID_WIKIDATA AND s.ID_PROPERTY = 'P21'
            AND (s.`RANK` IS NULL OR s.`RANK` <> 'deprecated') AND COALESCE(s.DELETED, 0) = 0 )
      END AS GENDER_QID,
      CASE WHEN P.PLACE_OF_BIRTH IS NULL OR P.PLACE_OF_BIRTH = '' THEN
        ( SELECT CASE WHEN COUNT(DISTINCT pv.ID_ITEM) = 1 THEN MIN(pv.ID_ITEM) END
          FROM T_WC_WIKIDATA_STATEMENT s
          INNER JOIN T_WC_WIKIDATA_ITEM_VALUE pv ON pv.ID_STATEMENT = s.ID_STATEMENT
          WHERE s.ID_WIKIDATA = P.ID_WIKIDATA AND s.ID_PROPERTY = 'P19'
            AND (s.`RANK` IS NULL OR s.`RANK` <> 'deprecated') AND COALESCE(s.DELETED, 0) = 0 )
      END AS PLACE_QID
      FROM T_WC_TMDB_PERSON P
      WHERE P.ID_WIKIDATA LIKE 'Q%'
        AND COALESCE(P.DELETED, 0) = 0
        /* At least one field to fill, before any Wikidata lookup. */
        AND ( (P.DEATHDAY IS NULL AND P.DEATH_YEAR IS NULL)
              OR (P.BIRTHDAY IS NULL AND P.BIRTH_YEAR IS NULL)
              OR COALESCE(P.GENDER, 0) = 0
              OR P.PLACE_OF_BIRTH IS NULL OR P.PLACE_OF_BIRTH = '' )
        /* GUARD 1: Wikidata points back at this TMDb record. */
        AND ( EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_STATEMENT sv
                       INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE ev ON ev.ID_STATEMENT = sv.ID_STATEMENT
                       WHERE sv.ID_WIKIDATA = P.ID_WIKIDATA AND sv.ID_PROPERTY = 'P4985'
                         AND (sv.`RANK` IS NULL OR sv.`RANK` <> 'deprecated')
                         AND ev.VALUE_EXTERNAL_ID = CONVERT(P.ID_PERSON, CHAR) COLLATE utf8mb4_unicode_ci )
              OR ( P.ID_IMDB LIKE 'nm%'
                   AND EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_STATEMENT si
                                INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE iv ON iv.ID_STATEMENT = si.ID_STATEMENT
                                WHERE si.ID_WIKIDATA = P.ID_WIKIDATA AND si.ID_PROPERTY = 'P345'
                                  AND (si.`RANK` IS NULL OR si.`RANK` <> 'deprecated')
                                  AND iv.VALUE_EXTERNAL_ID = P.ID_IMDB ) ) )
        /* GUARD 2: a TMDb date that contradicts Wikidata disqualifies the QID. */
        AND NOT EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_STATEMENT sb
                         INNER JOIN T_WC_WIKIDATA_TIME_VALUE tb ON tb.ID_STATEMENT = sb.ID_STATEMENT
                         WHERE P.BIRTHDAY IS NOT NULL
                           AND sb.ID_WIKIDATA = P.ID_WIKIDATA AND sb.ID_PROPERTY = 'P569'
                           AND (sb.`RANK` IS NULL OR sb.`RANK` <> 'deprecated')
                           AND tb.TIME_PRECISION = 11
                           AND (tb.YEAR_VALUE * 10000 + tb.MONTH_VALUE * 100 + tb.DAY_VALUE)
                               <> (YEAR(P.BIRTHDAY) * 10000 + MONTH(P.BIRTHDAY) * 100 + DAY(P.BIRTHDAY)) )
        AND NOT EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_STATEMENT sd
                         INNER JOIN T_WC_WIKIDATA_TIME_VALUE td ON td.ID_STATEMENT = sd.ID_STATEMENT
                         WHERE P.DEATHDAY IS NOT NULL
                           AND sd.ID_WIKIDATA = P.ID_WIKIDATA AND sd.ID_PROPERTY = 'P570'
                           AND (sd.`RANK` IS NULL OR sd.`RANK` <> 'deprecated')
                           AND td.TIME_PRECISION = 11
                           AND (td.YEAR_VALUE * 10000 + td.MONTH_VALUE * 100 + td.DAY_VALUE)
                               <> (YEAR(P.DEATHDAY) * 10000 + MONTH(P.DEATHDAY) * 100 + DAY(P.DEATHDAY)) )
    ) e
    ) h
  ) g
) f
LEFT JOIN T_WC_WIKIDATA_ITEM pl ON pl.ID_WIKIDATA = f.PLACE_QID
LEFT JOIN T_WC_WIKIDATA_ITEM co ON co.ID_WIKIDATA = f.COUNTRY_QID
LEFT JOIN T_WC_WIKIDATA_ITEM rg ON rg.ID_WIKIDATA = f.REGION_QID
LEFT JOIN T_WC_COUNTRY cc ON cc.ID_WIKIDATA = f.COUNTRY_QID AND cc.IS_DEFUNCT = 0
) y
LEFT JOIN T_WC_COUNTRY hc ON hc.COUNTRY_CODE = y.AT_BIRTH AND hc.IS_DEFUNCT = 1
) x
WHERE x.DATE_OF_DEATH IS NOT NULL OR x.DATE_OF_BIRTH IS NOT NULL
   OR x.GENDER IS NOT NULL OR x.PLACE_OF_BIRTH IS NOT NULL
ORDER BY x.POPULARITY DESC, x.ID_PERSON ASC
