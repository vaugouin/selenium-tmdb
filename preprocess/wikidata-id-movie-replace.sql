/*
Retrieve all movies whose ID_WIKIDATA in T_WC_TMDB_MOVIE is a VALID QID but DIFFERENT
from the one Wikidata carries for the same IMDb id, and only when Wikidata itself
names this very TMDb record. CSV export of this query is later used to CORRECT TMDb
records using python and Selenium.

CE FICHIER EST LE JUMEAU RISQUE DE wikidata-id-movie-fix.sql. Les deux se partagent la
population : le fix REMPLIT une case vide ou illisible, celui-ci REMPLACE une valeur
valide. La difference n'est pas de degre. Remplir n'ajoute que de l'information,
remplacer en detruit, et la destruction a lieu sur un site tiers, pilotee par un robot
qui ne relit rien. D'ou un fichier separe plutot qu'un garde retire : les deux
populations restent mesurables, recettables et interruptibles l'une sans l'autre.

⚠ LE ROBOT ECRASE SANS REGARDER. write_wikidata_id() dans le carnet fait field.clear()
puis saisit. Rien dans la chaine, apres cette requete, ne verifie ce qui est efface.
Le tri se fait donc ICI, en entier.

LA PREUVE EXIGEE POUR REMPLACER, garde 3 ci-dessous. Le rapprochement de base se fait
par IMDb : Wikidata connait P345, TMDb connait ID_IMDB, on en deduit un QID. Cela
suffit a remplir une case vide, pas a en contredire une pleine. On demande donc une
corroboration dans l'autre sens : que le QID candidat porte lui-meme, en P4947, le
numero de CETTE fiche TMDb. Les deux bases se designent alors mutuellement.

Mesure du 2026-09-05 sur les films, 752 remplacements possibles :
    A. Wikidata designe cette fiche, corrobore .... 659  (87,6 %, exportes ici)
    B. Wikidata ne connait aucun id TMDb .......... 73   (aucune preuve, ecartes)
    C. Wikidata designe une AUTRE fiche ........... 20   (contre-indication, ecartes)
Le cas C est le plus instructif : sans le garde 3, le robot aurait pose sur 20 fiches
un QID dont Wikidata dit qu'il appartient a une autre. Ce sont des doublons TMDb, et
l'ecriture en aurait fait des doublons de QID.

Le rang 'deprecated' est ecarte : Wikidata tient ces valeurs pour fausses, et il
serait malvenu d'aller les recopier sur TMDb.

⚠ CE FICHIER EST EXECUTE CHAQUE MATIN par le processus 1 de selenium-tmdb.py, qui
parcourt tous les .sql voisins et lance chacun par un UNIQUE cursor.execute(). Ne
jamais y enchainer plusieurs instructions, ne jamais deposer ici un fichier qui n'est
pas destine a s'executer. Voir AGENTS.md, section « SQL files ».
*/
SELECT DISTINCT
M1.ID_MOVIE AS ID_MOVIE,
WM.ID_WIKIDATA AS ID_WIKIDATA,
imdb.VALUE_EXTERNAL_ID AS ID_IMDB,
/* Meme colonne que dans le fix, pour que les deux CSV se lisent cote a cote. Le
   garde 3 la contraint a valoir ID_MOVIE, sauf dans le cas rare ou l'entite porte
   PLUSIEURS P4947 : la jointure retient celui qui corrobore, cette sous-requete
   rend le premier par rang. Un ecart entre les deux colonnes signale donc une entite
   Wikidata qui revendique plusieurs fiches TMDb, ce qui merite un oeil. */
( SELECT ev.VALUE_EXTERNAL_ID
  FROM T_WC_WIKIDATA_STATEMENT sv
  INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE ev ON ev.ID_STATEMENT = sv.ID_STATEMENT
  WHERE sv.ID_WIKIDATA = WM.ID_WIKIDATA AND sv.ID_PROPERTY = 'P4947'
    AND (sv.`RANK` IS NULL OR sv.`RANK` <> 'deprecated')
  ORDER BY (sv.`RANK` = 'preferred') DESC, sv.ID_STATEMENT ASC
  LIMIT 1 ) AS ID_WIKIDATA_MOVIE,
M1.ID_WIKIDATA AS ID_TMDB_WIKIDATA,
M1.TITLE AS TITLE,
M1.ADULT AS ADULT,
M2.ID_MOVIE AS ID_MOVIE_ERASE_WIKIDATA_ID
FROM T_WC_WIKIDATA_MOVIE WM
INNER JOIN T_WC_WIKIDATA_STATEMENT si ON si.ID_WIKIDATA = WM.ID_WIKIDATA
       AND si.ID_PROPERTY = 'P345'
       AND (si.`RANK` IS NULL OR si.`RANK` <> 'deprecated')
INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE imdb ON imdb.ID_STATEMENT = si.ID_STATEMENT
INNER JOIN T_WC_TMDB_MOVIE M1 ON imdb.VALUE_EXTERNAL_ID = M1.ID_IMDB
LEFT JOIN T_WC_TMDB_MOVIE M2 ON WM.ID_WIKIDATA = M2.ID_WIKIDATA
/* ⚠ GARDE 3 : LA CORROBORATION, ET C'EST CE QUI DISTINGUE CE FICHIER DU FIX.
   En jointure et non en WHERE, pour que le filtre s'applique avant le reste plutot
   qu'apres, et pour s'appuyer sur l'index de ID_WIKIDATA puis de ID_STATEMENT.
   La comparaison finale est numerique, VALUE_EXTERNAL_ID etant une chaine et
   ID_MOVIE un entier : c'est voulu, un CAST vers CHAR fabriquerait une valeur de
   collation utf8mb4_general_ci et leverait l'erreur 1267 contre une colonne en
   utf8mb4_unicode_ci. */
INNER JOIN T_WC_WIKIDATA_STATEMENT sc ON sc.ID_WIKIDATA = WM.ID_WIKIDATA
       AND sc.ID_PROPERTY = 'P4947'
       AND (sc.`RANK` IS NULL OR sc.`RANK` <> 'deprecated')
INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE corrob ON corrob.ID_STATEMENT = sc.ID_STATEMENT
       AND corrob.VALUE_EXTERNAL_ID = M1.ID_MOVIE
/* ⚠ GARDE 1 : ECARTER LES IDENTIFIANTS IMDb AMBIGUS.

   Mesure du 2026-09-01 : 15 films recevaient DEUX QID differents, parfois trois.
   « 24 Hrs Ghost Story » (tt0118538) se voyait proposer Q123330581, Q123330582 et
   Q123330588, trois identifiants consecutifs, donc des doublons crees en masse dans
   Wikidata. Sans ce garde, le robot les ecrirait en sequence sur la meme fiche TMDb
   et le dernier gagnerait au hasard de l'ordre de tri. On ne peut pas decider a la
   place de Wikidata lequel est le bon : on n'ecrit pas. Le garde vaut a plus forte
   raison ici, ou l'ecriture detruit une valeur existante.

   ⚠ ECRIT D'ABORD EN SOUS-REQUETE CORRELEE dans le fix, ce qui a fait tourner le
   conteneur plus d'une heure le 2026-09-02. La cause tient a une colonne :
   T_WC_WIKIDATA_EXTERNAL_ID_VALUE.VALUE_EXTERNAL_ID N'EST PAS INDEXEE, seule
   VALUE_EXTERNAL_ID_NORMALIZED(255) l'est. La table derivee ci-dessous calcule
   l'ensemble des identifiants ambigus UNE SEULE FOIS. */
LEFT JOIN (
      SELECT e2.VALUE_EXTERNAL_ID AS AMBIGU
      FROM T_WC_WIKIDATA_EXTERNAL_ID_VALUE e2
      INNER JOIN T_WC_WIKIDATA_STATEMENT s2 ON s2.ID_STATEMENT = e2.ID_STATEMENT
             AND s2.ID_PROPERTY = 'P345'
             AND (s2.`RANK` IS NULL OR s2.`RANK` <> 'deprecated')
      INNER JOIN T_WC_WIKIDATA_MOVIE w2 ON w2.ID_WIKIDATA = s2.ID_WIKIDATA
      GROUP BY e2.VALUE_EXTERNAL_ID
      HAVING COUNT(DISTINCT w2.ID_WIKIDATA) > 1
) amb ON amb.AMBIGU = imdb.VALUE_EXTERNAL_ID
WHERE imdb.VALUE_EXTERNAL_ID IS NOT NULL AND imdb.VALUE_EXTERNAL_ID <> ''
AND imdb.VALUE_EXTERNAL_ID LIKE 'tt%'
AND amb.AMBIGU IS NULL
/* ⚠ GARDE 2, INVERSE DE CELUI DU FIX. Le fix ne prend que le vide et l'illisible,
   celui-ci ne prend que le contraire : une valeur presente, bien formee, et
   differente de ce que Wikidata porte. Les deux populations sont donc disjointes,
   et leur reunion est exactement celle que la requete d'origine visait. */
AND M1.ID_WIKIDATA REGEXP '^Q[0-9]+$'
AND M1.ID_WIKIDATA <> WM.ID_WIKIDATA
/*
AND M1.ADULT = 0
 */
ORDER BY M1.ID_MOVIE ASC
