-- ============================================================================
-- SELENIUM-TMDB-012 : ce que la bascule V1 vers V2 change aux trois exports
-- ============================================================================
--
-- ⚠ POURQUOI CETTE RECETTE COMPTE PLUS QUE LES AUTRES DE CETTE MIGRATION. Les trois
-- requetes wikidata-id-*-fix.sql ne remplissent pas un ecran, elles pilotent un ROBOT
-- QUI ECRIT SUR TMDB. Une ligne de trop n'est pas une ligne affichee en trop, c'est
-- une modification poussee sur un site tiers, difficile a reprendre et visible par
-- d'autres. La regle est donc : lire les ecarts AVANT de lancer Selenium, jamais
-- apres.
--
-- ⚠ COLLATION. Lancer avec --force.
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- 1. VOLUME DES TROIS EXPORTS, V1 contre V2
--
--    Un ecart est attendu, dans les deux sens, et trois causes le produisent :
--      - V2 couvre plus d'entites que V1 sur certaines proprietes ;
--      - V2 en couvre moins hors du perimetre d'import (WIKIDATA-CRAWLER-011,
--        tranche le 2026-08-28, perte acceptee) ;
--      - le lien serie vers TMDb etait BOGUE en V1 : sur les series, l'ecart peut
--        etre une CORRECTION et non une perte.
-- ---------------------------------------------------------------------------
SELECT '1. Films, volume des deux exports' AS SECTION;

SET STATEMENT max_statement_time=180 FOR
SELECT 'V1' AS SOURCE, COUNT(*) AS LIGNES
FROM T_WC_WIKIDATA_MOVIE_V1 WM
INNER JOIN T_WC_TMDB_MOVIE M1 ON WM.ID_IMDB = M1.ID_IMDB
WHERE WM.ID_IMDB IS NOT NULL AND WM.ID_IMDB <> '' AND WM.ID_IMDB LIKE 'tt%'
  AND WM.ID_WIKIDATA <> M1.ID_WIKIDATA
  AND (M1.ID_WIKIDATA IS NULL OR M1.ID_WIKIDATA = '' OR M1.ID_WIKIDATA NOT REGEXP '^Q[0-9]+$');

SET STATEMENT max_statement_time=180 FOR
SELECT 'V2' AS SOURCE, COUNT(*) AS LIGNES
FROM T_WC_WIKIDATA_MOVIE WM
INNER JOIN T_WC_WIKIDATA_STATEMENT si ON si.ID_WIKIDATA = WM.ID_WIKIDATA
       AND si.ID_PROPERTY = 'P345'
       AND (si.`RANK` IS NULL OR si.`RANK` <> 'deprecated')
INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE imdb ON imdb.ID_STATEMENT = si.ID_STATEMENT
INNER JOIN T_WC_TMDB_MOVIE M1 ON imdb.VALUE_EXTERNAL_ID = M1.ID_IMDB
WHERE imdb.VALUE_EXTERNAL_ID LIKE 'tt%'
  AND WM.ID_WIKIDATA <> M1.ID_WIKIDATA
  AND (M1.ID_WIKIDATA IS NULL OR M1.ID_WIKIDATA = '' OR M1.ID_WIKIDATA NOT REGEXP '^Q[0-9]+$');

SELECT '2. Series, volume des deux exports' AS SECTION;

SET STATEMENT max_statement_time=180 FOR
SELECT 'V1' AS SOURCE, COUNT(*) AS LIGNES
FROM T_WC_WIKIDATA_SERIE_V1 WS
INNER JOIN T_WC_TMDB_SERIE S1 ON WS.ID_IMDB = S1.ID_IMDB
WHERE WS.ID_IMDB IS NOT NULL AND WS.ID_IMDB <> '' AND WS.ID_IMDB LIKE 'tt%'
  AND WS.ID_WIKIDATA <> S1.ID_WIKIDATA
  AND (S1.ID_WIKIDATA IS NULL OR S1.ID_WIKIDATA = '' OR S1.ID_WIKIDATA NOT REGEXP '^Q[0-9]+$');

SET STATEMENT max_statement_time=180 FOR
SELECT 'V2' AS SOURCE, COUNT(*) AS LIGNES
FROM T_WC_WIKIDATA_SERIE WS
INNER JOIN T_WC_WIKIDATA_STATEMENT si ON si.ID_WIKIDATA = WS.ID_WIKIDATA
       AND si.ID_PROPERTY = 'P345'
       AND (si.`RANK` IS NULL OR si.`RANK` <> 'deprecated')
INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE imdb ON imdb.ID_STATEMENT = si.ID_STATEMENT
INNER JOIN T_WC_TMDB_SERIE S1 ON imdb.VALUE_EXTERNAL_ID = S1.ID_IMDB
WHERE imdb.VALUE_EXTERNAL_ID LIKE 'tt%'
  AND WS.ID_WIKIDATA <> S1.ID_WIKIDATA
  AND (S1.ID_WIKIDATA IS NULL OR S1.ID_WIKIDATA = '' OR S1.ID_WIKIDATA NOT REGEXP '^Q[0-9]+$');

SELECT '3. Personnes, volume des deux exports' AS SECTION;

SET STATEMENT max_statement_time=180 FOR
SELECT 'V1' AS SOURCE, COUNT(*) AS LIGNES
FROM T_WC_WIKIDATA_PERSON_V1 WP
INNER JOIN T_WC_TMDB_PERSON P1 ON WP.ID_IMDB = P1.ID_IMDB
WHERE WP.ID_IMDB IS NOT NULL AND WP.ID_IMDB <> '' AND WP.ID_IMDB LIKE 'nm%'
  AND WP.ID_WIKIDATA <> P1.ID_WIKIDATA
  AND (P1.ID_WIKIDATA IS NULL OR P1.ID_WIKIDATA = '' OR P1.ID_WIKIDATA NOT REGEXP '^Q[0-9]+$')
  AND WP.ID_WIKIDATA NOT IN ('Q11473776');

SET STATEMENT max_statement_time=180 FOR
SELECT 'V2' AS SOURCE, COUNT(*) AS LIGNES
FROM T_WC_WIKIDATA_PERSON WP
INNER JOIN T_WC_WIKIDATA_STATEMENT si ON si.ID_WIKIDATA = WP.ID_WIKIDATA
       AND si.ID_PROPERTY = 'P345'
       AND (si.`RANK` IS NULL OR si.`RANK` <> 'deprecated')
INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE imdb ON imdb.ID_STATEMENT = si.ID_STATEMENT
INNER JOIN T_WC_TMDB_PERSON P1 ON imdb.VALUE_EXTERNAL_ID = P1.ID_IMDB
WHERE imdb.VALUE_EXTERNAL_ID LIKE 'nm%'
  AND WP.ID_WIKIDATA <> P1.ID_WIKIDATA
  AND (P1.ID_WIKIDATA IS NULL OR P1.ID_WIKIDATA = '' OR P1.ID_WIKIDATA NOT REGEXP '^Q[0-9]+$')
  AND WP.ID_WIKIDATA NOT IN ('Q11473776');

-- ---------------------------------------------------------------------------
-- 4. LES FILMS QUE V2 AJOUTE, à lire un par un avant de lancer le robot.
--    Ce sont les modifications que Selenium poussera et que V1 ne poussait pas.
-- ---------------------------------------------------------------------------
SELECT '4. Vingt films que V2 ajoute a l export' AS SECTION;

SET STATEMENT max_statement_time=180 FOR
SELECT M1.ID_MOVIE, M1.TITLE, WM.ID_WIKIDATA, imdb.VALUE_EXTERNAL_ID AS ID_IMDB
FROM T_WC_WIKIDATA_MOVIE WM
INNER JOIN T_WC_WIKIDATA_STATEMENT si ON si.ID_WIKIDATA = WM.ID_WIKIDATA
       AND si.ID_PROPERTY = 'P345'
       AND (si.`RANK` IS NULL OR si.`RANK` <> 'deprecated')
INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE imdb ON imdb.ID_STATEMENT = si.ID_STATEMENT
INNER JOIN T_WC_TMDB_MOVIE M1 ON imdb.VALUE_EXTERNAL_ID = M1.ID_IMDB
WHERE imdb.VALUE_EXTERNAL_ID LIKE 'tt%'
  AND WM.ID_WIKIDATA <> M1.ID_WIKIDATA
  AND (M1.ID_WIKIDATA IS NULL OR M1.ID_WIKIDATA = '' OR M1.ID_WIKIDATA NOT REGEXP '^Q[0-9]+$')
  AND NOT EXISTS ( SELECT 1 FROM T_WC_WIKIDATA_MOVIE_V1 v1
                   WHERE v1.ID_WIKIDATA = WM.ID_WIKIDATA )
LIMIT 20;

-- ---------------------------------------------------------------------------
-- 5. ⚠ UN DEFAUT PREEXISTANT, TROUVE EN MIGRANT ET DELIBEREMENT PAS CORRIGE.
--
--    Les trois requetes portent, cote a cote, ces deux conditions :
--
--        AND WM.ID_WIKIDATA <> M1.ID_WIKIDATA
--        AND (M1.ID_WIKIDATA IS NULL OR M1.ID_WIKIDATA = '' OR ... NOT REGEXP ...)
--
--    La seconde prevoit EXPLICITEMENT le cas NULL. La premiere l'elimine : en SQL,
--    NULL <> 'Q123' ne vaut pas vrai, il vaut NULL, et le WHERE rejette la ligne.
--    L'export ne remonte donc JAMAIS les entites dont l'ID_WIKIDATA cote TMDb est
--    NULL, alors que ce sont precisement celles que la requete dit chercher. Seules
--    sortent les chaines vides et les valeurs mal formees.
--
--    C'est la troisieme fois que cette migration bute sur le meme piege : le 0
--    sentinelle du numero Criterion, le IS NOT NULL qui comptait les zeros, et
--    maintenant ceci. NULL n'est pas une valeur, c'est l'absence de valeur, et
--    toute comparaison avec lui rend NULL.
--
--    ⚠ POURQUOI JE NE LE CORRIGE PAS. Corriger ferait grossir la population d'un
--    robot qui ECRIT sur un site tiers, peut-etre beaucoup. C'est une decision de
--    Philippe, pas un effet de bord d'une migration. La requete ci-dessous chiffre
--    ce que la correction ajouterait, pour qu'il decide sur un nombre.
-- ---------------------------------------------------------------------------
SELECT '5. Ce que corriger le piege NULL ajouterait a l export des films' AS SECTION;

SET STATEMENT max_statement_time=180 FOR
SELECT COUNT(*) AS LIGNES_AUJOURD_HUI_INVISIBLES
FROM T_WC_WIKIDATA_MOVIE WM
INNER JOIN T_WC_WIKIDATA_STATEMENT si ON si.ID_WIKIDATA = WM.ID_WIKIDATA
       AND si.ID_PROPERTY = 'P345'
       AND (si.`RANK` IS NULL OR si.`RANK` <> 'deprecated')
INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE imdb ON imdb.ID_STATEMENT = si.ID_STATEMENT
INNER JOIN T_WC_TMDB_MOVIE M1 ON imdb.VALUE_EXTERNAL_ID = M1.ID_IMDB
WHERE imdb.VALUE_EXTERNAL_ID LIKE 'tt%'
  AND M1.ID_WIKIDATA IS NULL;
