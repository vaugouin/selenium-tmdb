/*
Retrieve all persons with empty or wrong ID_WIKIDATA in T_WC_TMDB_PERSON
when Wikidata knows the entity, matching on ID_IMDB.
CSV export of this query is later used for fix of TMDb records using python and Selenium

CE QUE CE SCRIPT CHERCHE, deux choses et non une :
  1. une entite TMDb SANS identifiant Wikidata : absent, vide ou mal forme ;
  2. une entite TMDb dont l'identifiant Wikidata est FAUX.
Les deux etaient relies par ET jusqu'au 2026-09-01, ce qui rendait le cas 1
inatteignable des que l'identifiant valait NULL, NULL <> 'Q123' valant NULL et non
vrai. Corrige en OU.

MIGRATION WIKIDATA V1 VERS V2, 2026-09-01.
La requete lisait T_WC_WIKIDATA_PERSON_V1, ou ID_WIKIDATA, ID_IMDB et l'identifiant TMDb vivaient
dans trois colonnes de la meme ligne. En V2 les deux identifiants externes sont des
STATEMENTS, P345 pour IMDb et P4985 pour TMDb. D'ou une table d'entite et deux
jointures. L'identifiant IMDb est en INNER JOIN, il est la cle du rapprochement ;
celui de TMDb en sous-requete scalaire.

⚠ POURQUOI UNE SOUS-REQUETE ET NON UNE JOINTURE, corrige le 2026-09-02. En LEFT JOIN,
une entite portant DEUX statements TMDb produisait DEUX lignes pour le meme film, avec
le meme QID a ecrire : 46 doublons dans l'export du jour. Un SELECT DISTINCT n'y
pouvait rien, puisqu'il porte sur la ligne entiere et que c'est justement cette colonne
qui differait. La sous-requete rend UNE valeur, choisie par le rang puis l'ordre des
claims, et le DISTINCT devient un filet plutot qu'un remede.

Le rang 'deprecated' est ecarte : Wikidata tient ces valeurs pour fausses, et il
serait malvenu d'aller les recopier sur TMDb.

⚠ CE FICHIER EST EXECUTE CHAQUE MATIN par le processus 1 de selenium-tmdb.py, qui
parcourt tous les .sql voisins et lance chacun par un UNIQUE cursor.execute(). Ne
jamais y enchainer plusieurs instructions, ne jamais deposer ici un fichier qui n'est
pas destine a s'executer. Voir AGENTS.md, section « SQL files ».
*/
SELECT DISTINCT
P1.ID_PERSON AS ID_PERSON,
WP.ID_WIKIDATA AS ID_WIKIDATA,
imdb.VALUE_EXTERNAL_ID AS ID_IMDB,
( SELECT ev.VALUE_EXTERNAL_ID
  FROM T_WC_WIKIDATA_STATEMENT sv
  INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE ev ON ev.ID_STATEMENT = sv.ID_STATEMENT
  WHERE sv.ID_WIKIDATA = WP.ID_WIKIDATA AND sv.ID_PROPERTY = 'P4985'
    AND (sv.`RANK` IS NULL OR sv.`RANK` <> 'deprecated')
  ORDER BY (sv.`RANK` = 'preferred') DESC, sv.ID_STATEMENT ASC
  LIMIT 1 ) AS ID_WIKIDATA_PERSON,
P1.ID_WIKIDATA AS ID_TMDB_WIKIDATA,
P1.NAME AS NAME,
P1.ADULT AS ADULT,
P2.ID_PERSON AS ID_PERSON_ERASE_WIKIDATA_ID
FROM T_WC_WIKIDATA_PERSON WP
INNER JOIN T_WC_WIKIDATA_STATEMENT si ON si.ID_WIKIDATA = WP.ID_WIKIDATA
       AND si.ID_PROPERTY = 'P345'
       AND (si.`RANK` IS NULL OR si.`RANK` <> 'deprecated')
INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE imdb ON imdb.ID_STATEMENT = si.ID_STATEMENT
INNER JOIN T_WC_TMDB_PERSON P1 ON imdb.VALUE_EXTERNAL_ID = P1.ID_IMDB
LEFT JOIN T_WC_TMDB_PERSON P2 ON WP.ID_WIKIDATA = P2.ID_WIKIDATA
/* ⚠ GARDE 1 : ECARTER LES IDENTIFIANTS IMDb AMBIGUS.

   Mesure du 2026-09-01 : 15 films recevaient DEUX QID differents, parfois trois.
   « 24 Hrs Ghost Story » (tt0118538) se voyait proposer Q123330581, Q123330582 et
   Q123330588, trois identifiants consecutifs, donc des doublons crees en masse dans
   Wikidata. Sans ce garde, le robot les ecrirait en sequence sur la meme fiche TMDb
   et le dernier gagnerait au hasard de l'ordre de tri. On ne peut pas decider a la
   place de Wikidata lequel est le bon : on n'ecrit pas.

   ⚠ ECRIT D'ABORD EN SOUS-REQUETE CORRELEE, ce qui a fait tourner le conteneur plus
   d'une heure sans rendre la main, le 2026-09-02. La cause tient a une colonne :
   T_WC_WIKIDATA_EXTERNAL_ID_VALUE.VALUE_EXTERNAL_ID N'EST PAS INDEXEE, seule
   VALUE_EXTERNAL_ID_NORMALIZED(255) l'est. Comparer sur elle imposait un balayage
   complet de la table pour CHACUNE des 20 000 lignes candidates.

   La table derivee ci-dessous calcule l'ensemble des identifiants ambigus UNE SEULE
   FOIS. Le balayage a lieu une fois au lieu de vingt mille. */
LEFT JOIN (
      SELECT e2.VALUE_EXTERNAL_ID AS AMBIGU
      FROM T_WC_WIKIDATA_EXTERNAL_ID_VALUE e2
      INNER JOIN T_WC_WIKIDATA_STATEMENT s2 ON s2.ID_STATEMENT = e2.ID_STATEMENT
             AND s2.ID_PROPERTY = 'P345'
             AND (s2.`RANK` IS NULL OR s2.`RANK` <> 'deprecated')
      INNER JOIN T_WC_WIKIDATA_PERSON w2 ON w2.ID_WIKIDATA = s2.ID_WIKIDATA
      GROUP BY e2.VALUE_EXTERNAL_ID
      HAVING COUNT(DISTINCT w2.ID_WIKIDATA) > 1
) amb ON amb.AMBIGU = imdb.VALUE_EXTERNAL_ID
WHERE imdb.VALUE_EXTERNAL_ID IS NOT NULL AND imdb.VALUE_EXTERNAL_ID <> ''
AND imdb.VALUE_EXTERNAL_ID LIKE 'nm%'
AND amb.AMBIGU IS NULL
/* ⚠ GARDE 2 : NE PAS ECRASER UN IDENTIFIANT VALIDE DEJA POSE.
   Mesure du 2026-09-01 : 20 201 lignes remplissent une case VIDE, 751 remplaceraient
   un QID valide mais different. Les deux n'ont pas le meme risque, le premier
   n'ajoute que de l'information, le second en detruit. Le remplacement est desactive
   par defaut, le temps d'examiner les 751 cas. POUR LES REACTIVER, retirer la ligne
   ci-dessous et relancer la section 6D de test-012-selenium-v1-v2.sql. */
AND (P1.ID_WIKIDATA IS NULL OR P1.ID_WIKIDATA = '' OR P1.ID_WIKIDATA NOT REGEXP '^Q[0-9]+$')
/* Les deux cas cherches, en OU. */
AND (
     P1.ID_WIKIDATA IS NULL
  OR P1.ID_WIKIDATA = ''
  OR P1.ID_WIKIDATA NOT REGEXP '^Q[0-9]+$'
  OR P1.ID_WIKIDATA <> WP.ID_WIKIDATA
)
AND WP.ID_WIKIDATA NOT IN ('Q11473776')
/*
AND P1.ADULT = 0
 */
ORDER BY P1.ID_PERSON ASC
