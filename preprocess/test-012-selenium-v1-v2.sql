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
-- 5. ⚠ CE QUE LA CORRECTION DU PIEGE NULL AJOUTE, à lire AVANT de lancer le robot.
--
--    Le script cherche DEUX choses, et son commentaire d'en-tete le dit desormais :
--      1. une entite TMDb SANS identifiant Wikidata (absent, vide ou mal forme) ;
--      2. une entite TMDb dont l'identifiant Wikidata est FAUX.
--
--    Les deux conditions etaient reliees par ET, ce qui rendait le cas 1
--    inatteignable des que l'identifiant valait NULL : NULL <> 'Q123' ne vaut pas
--    vrai, il vaut NULL, et le WHERE rejette. Or la colonne accepte NULL. Le script
--    ne servait donc que la moitie de son objet. Corrige en OU le 2026-09-01.
--
--    ⚠ CETTE CORRECTION FAIT GROSSIR LA POPULATION D'UN ROBOT QUI ECRIT SUR TMDB.
--    Les trois requetes ci-dessous chiffrent de combien, par entite. Si le nombre
--    surprend, lancer Selenium sur un echantillon avant le lot complet.
-- ---------------------------------------------------------------------------
SELECT '5. Lignes qu ajoute la correction du piege NULL' AS SECTION;

SET STATEMENT max_statement_time=180 FOR
SELECT 'films' AS ENTITE, COUNT(*) AS AJOUTEES
FROM T_WC_WIKIDATA_MOVIE WM
INNER JOIN T_WC_WIKIDATA_STATEMENT si ON si.ID_WIKIDATA = WM.ID_WIKIDATA
       AND si.ID_PROPERTY = 'P345'
       AND (si.`RANK` IS NULL OR si.`RANK` <> 'deprecated')
INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE imdb ON imdb.ID_STATEMENT = si.ID_STATEMENT
INNER JOIN T_WC_TMDB_MOVIE M1 ON imdb.VALUE_EXTERNAL_ID = M1.ID_IMDB
WHERE imdb.VALUE_EXTERNAL_ID LIKE 'tt%' AND M1.ID_WIKIDATA IS NULL;

SET STATEMENT max_statement_time=180 FOR
SELECT 'series' AS ENTITE, COUNT(*) AS AJOUTEES
FROM T_WC_WIKIDATA_SERIE WS
INNER JOIN T_WC_WIKIDATA_STATEMENT si ON si.ID_WIKIDATA = WS.ID_WIKIDATA
       AND si.ID_PROPERTY = 'P345'
       AND (si.`RANK` IS NULL OR si.`RANK` <> 'deprecated')
INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE imdb ON imdb.ID_STATEMENT = si.ID_STATEMENT
INNER JOIN T_WC_TMDB_SERIE S1 ON imdb.VALUE_EXTERNAL_ID = S1.ID_IMDB
WHERE imdb.VALUE_EXTERNAL_ID LIKE 'tt%' AND S1.ID_WIKIDATA IS NULL;

SET STATEMENT max_statement_time=180 FOR
SELECT 'personnes' AS ENTITE, COUNT(*) AS AJOUTEES
FROM T_WC_WIKIDATA_PERSON WP
INNER JOIN T_WC_WIKIDATA_STATEMENT si ON si.ID_WIKIDATA = WP.ID_WIKIDATA
       AND si.ID_PROPERTY = 'P345'
       AND (si.`RANK` IS NULL OR si.`RANK` <> 'deprecated')
INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE imdb ON imdb.ID_STATEMENT = si.ID_STATEMENT
INNER JOIN T_WC_TMDB_PERSON P1 ON imdb.VALUE_EXTERNAL_ID = P1.ID_IMDB
WHERE imdb.VALUE_EXTERNAL_ID LIKE 'nm%' AND P1.ID_WIKIDATA IS NULL
  AND WP.ID_WIKIDATA NOT IN ('Q11473776');

-- ---------------------------------------------------------------------------
-- 6. ⚠ LE VOLUME A EXPLOSÉ : contrôles à passer AVANT de lancer le robot.
--
--    Passage du 2026-09-01 : films 108 -> 20 214, séries 160 -> 2 839, personnes
--    124 -> 11 544. La section 5 rendant 0, ce n'est pas la correction du piège NULL
--    qui les produit, c'est la bascule elle-même : V2 connaît beaucoup plus
--    d'entités que le crawl SPARQL de V1.
--
--    Mais un facteur 187 se vérifie avant de s'accepter, et deux causes possibles
--    doivent être écartées, parce qu'elles produiraient le même symptôme :
--      A. une entité Wikidata portant PLUSIEURS statements P345 : la jointure
--         multiplie alors les lignes sans que l'export gagne un seul film ;
--      B. plusieurs entités Wikidata partageant le MÊME identifiant IMDb : le robot
--         écrirait alors deux QID différents sur la même fiche TMDb, en séquence,
--         et le dernier gagnerait au hasard de l'ordre.
--
--    Ces deux cas sont pires que du volume : ce sont des écritures fausses sur un
--    site tiers. Les deux requêtes ci-dessous les comptent.
-- ---------------------------------------------------------------------------
SELECT '6A. Films : lignes exportees contre films distincts (les deux doivent etre egaux)' AS SECTION;

SET STATEMENT max_statement_time=180 FOR
SELECT COUNT(*) AS LIGNES, COUNT(DISTINCT M1.ID_MOVIE) AS FILMS_DISTINCTS
FROM T_WC_WIKIDATA_MOVIE WM
INNER JOIN T_WC_WIKIDATA_STATEMENT si ON si.ID_WIKIDATA = WM.ID_WIKIDATA
       AND si.ID_PROPERTY = 'P345'
       AND (si.`RANK` IS NULL OR si.`RANK` <> 'deprecated')
INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE imdb ON imdb.ID_STATEMENT = si.ID_STATEMENT
INNER JOIN T_WC_TMDB_MOVIE M1 ON imdb.VALUE_EXTERNAL_ID = M1.ID_IMDB
WHERE imdb.VALUE_EXTERNAL_ID LIKE 'tt%'
  AND ( M1.ID_WIKIDATA IS NULL OR M1.ID_WIKIDATA = ''
     OR M1.ID_WIKIDATA NOT REGEXP '^Q[0-9]+$' OR M1.ID_WIKIDATA <> WM.ID_WIKIDATA );

SELECT '6B. Films recevant DEUX QID differents : le robot ecrirait au hasard (attendu : 0)' AS SECTION;

SET STATEMENT max_statement_time=180 FOR
SELECT COUNT(*) AS FILMS_AMBIGUS FROM (
  SELECT M1.ID_MOVIE
  FROM T_WC_WIKIDATA_MOVIE WM
  INNER JOIN T_WC_WIKIDATA_STATEMENT si ON si.ID_WIKIDATA = WM.ID_WIKIDATA
         AND si.ID_PROPERTY = 'P345'
         AND (si.`RANK` IS NULL OR si.`RANK` <> 'deprecated')
  INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE imdb ON imdb.ID_STATEMENT = si.ID_STATEMENT
  INNER JOIN T_WC_TMDB_MOVIE M1 ON imdb.VALUE_EXTERNAL_ID = M1.ID_IMDB
  WHERE imdb.VALUE_EXTERNAL_ID LIKE 'tt%'
    AND ( M1.ID_WIKIDATA IS NULL OR M1.ID_WIKIDATA = ''
       OR M1.ID_WIKIDATA NOT REGEXP '^Q[0-9]+$' OR M1.ID_WIKIDATA <> WM.ID_WIKIDATA )
  GROUP BY M1.ID_MOVIE
  HAVING COUNT(DISTINCT WM.ID_WIKIDATA) > 1 ) a;

SELECT '6C. Dix films ambigus, s il y en a : a regarder un par un' AS SECTION;

SET STATEMENT max_statement_time=180 FOR
SELECT M1.ID_MOVIE, M1.TITLE, M1.ID_IMDB,
       GROUP_CONCAT(DISTINCT WM.ID_WIKIDATA ORDER BY WM.ID_WIKIDATA) AS QID_CANDIDATS
FROM T_WC_WIKIDATA_MOVIE WM
INNER JOIN T_WC_WIKIDATA_STATEMENT si ON si.ID_WIKIDATA = WM.ID_WIKIDATA
       AND si.ID_PROPERTY = 'P345'
       AND (si.`RANK` IS NULL OR si.`RANK` <> 'deprecated')
INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE imdb ON imdb.ID_STATEMENT = si.ID_STATEMENT
INNER JOIN T_WC_TMDB_MOVIE M1 ON imdb.VALUE_EXTERNAL_ID = M1.ID_IMDB
WHERE imdb.VALUE_EXTERNAL_ID LIKE 'tt%'
  AND ( M1.ID_WIKIDATA IS NULL OR M1.ID_WIKIDATA = ''
     OR M1.ID_WIKIDATA NOT REGEXP '^Q[0-9]+$' OR M1.ID_WIKIDATA <> WM.ID_WIKIDATA )
GROUP BY M1.ID_MOVIE, M1.TITLE, M1.ID_IMDB
HAVING COUNT(DISTINCT WM.ID_WIKIDATA) > 1
LIMIT 10;

SELECT '6D. Quelle part des 20 214 est une CORRECTION et non un ajout' AS SECTION;

-- Un film qui portait deja un QID valide mais DIFFERENT est un cas plus delicat :
-- le robot va ecraser une valeur existante. Les distinguer permet de commencer par
-- les ajouts, qui ne detruisent rien, et de traiter les remplacements ensuite.
SET STATEMENT max_statement_time=180 FOR
SELECT CASE
         WHEN M1.ID_WIKIDATA IS NULL OR M1.ID_WIKIDATA = '' THEN 'AJOUT (case vide)'
         WHEN M1.ID_WIKIDATA NOT REGEXP '^Q[0-9]+$' THEN 'AJOUT (valeur mal formee)'
         ELSE 'REMPLACEMENT (QID valide mais different)'
       END AS NATURE,
       COUNT(DISTINCT M1.ID_MOVIE) AS FILMS
FROM T_WC_WIKIDATA_MOVIE WM
INNER JOIN T_WC_WIKIDATA_STATEMENT si ON si.ID_WIKIDATA = WM.ID_WIKIDATA
       AND si.ID_PROPERTY = 'P345'
       AND (si.`RANK` IS NULL OR si.`RANK` <> 'deprecated')
INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE imdb ON imdb.ID_STATEMENT = si.ID_STATEMENT
INNER JOIN T_WC_TMDB_MOVIE M1 ON imdb.VALUE_EXTERNAL_ID = M1.ID_IMDB
WHERE imdb.VALUE_EXTERNAL_ID LIKE 'tt%'
  AND ( M1.ID_WIKIDATA IS NULL OR M1.ID_WIKIDATA = ''
     OR M1.ID_WIKIDATA NOT REGEXP '^Q[0-9]+$' OR M1.ID_WIKIDATA <> WM.ID_WIKIDATA )
GROUP BY NATURE;
