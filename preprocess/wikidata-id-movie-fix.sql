/*
Retrieve all movies with empty ID_WIKIDATA in T_WC_TMDB_MOVIE
when Wikidata knows the entity, matching on ID_IMDB.
CSV export of this query is later used for fix of TMDb records using python and Selenium

MIGRATION WIKIDATA V1 VERS V2, 2026-09-01.
La requete lisait T_WC_WIKIDATA_MOVIE_V1, ou ID_WIKIDATA, ID_IMDB et l'identifiant
TMDb vivaient dans trois colonnes de la meme ligne. En V2 ces trois faits sont ranges
autrement : l'entite porte son ID_WIKIDATA dans sa table, et les deux identifiants
externes sont des STATEMENTS, P345 pour IMDb et P4947 pour TMDb. D'ou la forme
ci-dessous, une table d'entite et deux jointures.

⚠ CE QUE LA BASCULE PEUT CHANGER, ET QU'IL FAUT MESURER AVANT DE LANCER SELENIUM.
Cette requete pilote un ROBOT qui ECRIT sur TMDb. Une ligne de trop n'est pas une
ligne affichee en trop, c'est une modification poussee sur un site tiers. Le fichier
compagnon test-012-selenium-v1-v2.sql compare les deux populations et liste les
lignes que V2 ajoute : les lire avant de lancer la premiere fois.

Trois raisons possibles a un ecart, toutes documentees ailleurs :
  - V2 couvre PLUS d'entites que V1 sur certaines proprietes (les cles Plex des
    series gagnaient 561 lignes, mesure du 2026-08-26) ;
  - V2 en couvre MOINS quand l'entite est hors du perimetre d'import
    (WIKIDATA-CRAWLER-011, tranche le 2026-08-28, perte acceptee) ;
  - le lien serie vers TMDb etait BOGUE en V1, ce que la validation V1 contre V2
    avait releve : sur les series, l'ecart peut donc etre une CORRECTION.

Le rang 'deprecated' est ecarte : Wikidata tient ces valeurs pour fausses, et il
serait malvenu d'aller les recopier sur TMDb.
*/

SELECT
M1.ID_MOVIE AS ID_MOVIE,
WM.ID_WIKIDATA AS ID_WIKIDATA,
imdb.VALUE_EXTERNAL_ID AS ID_IMDB,
tmdb.VALUE_EXTERNAL_ID AS ID_WIKIDATA_MOVIE,
M1.ID_WIKIDATA AS ID_TMDB_WIKIDATA,
M1.TITLE AS TITLE,
M1.ADULT AS ADULT,
M2.ID_MOVIE AS ID_MOVIE_ERASE_WIKIDATA_ID
FROM T_WC_WIKIDATA_MOVIE WM
/* L'identifiant IMDb, obligatoire : c'est la cle du rapprochement. */
INNER JOIN T_WC_WIKIDATA_STATEMENT si ON si.ID_WIKIDATA = WM.ID_WIKIDATA
       AND si.ID_PROPERTY = 'P345'
       AND (si.`RANK` IS NULL OR si.`RANK` <> 'deprecated')
INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE imdb ON imdb.ID_STATEMENT = si.ID_STATEMENT
/* L'identifiant TMDb, facultatif : la colonne V1 etait souvent vide et le CSV
   l'exporte a titre indicatif, jamais comme condition. Un INNER JOIN ici
   retirerait des lignes que V1 produisait. */
LEFT JOIN T_WC_WIKIDATA_STATEMENT st ON st.ID_WIKIDATA = WM.ID_WIKIDATA
      AND st.ID_PROPERTY = 'P4947'
      AND (st.`RANK` IS NULL OR st.`RANK` <> 'deprecated')
LEFT JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE tmdb ON tmdb.ID_STATEMENT = st.ID_STATEMENT
INNER JOIN T_WC_TMDB_MOVIE M1 ON imdb.VALUE_EXTERNAL_ID = M1.ID_IMDB
LEFT JOIN T_WC_TMDB_MOVIE M2 ON WM.ID_WIKIDATA = M2.ID_WIKIDATA
WHERE imdb.VALUE_EXTERNAL_ID IS NOT NULL AND imdb.VALUE_EXTERNAL_ID <> ''
AND imdb.VALUE_EXTERNAL_ID LIKE 'tt%'
AND WM.ID_WIKIDATA <> M1.ID_WIKIDATA
AND (M1.ID_WIKIDATA IS NULL OR M1.ID_WIKIDATA = '' OR M1.ID_WIKIDATA NOT REGEXP '^Q[0-9]+$')
/*
AND M1.ADULT = 0
 */
ORDER BY M1.ID_MOVIE ASC
