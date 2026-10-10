/*
Retrieve all persons with empty or wrong ID_WIKIDATA in T_WC_TMDB_PERSON
when Wikidata knows the entity, matching on ID_IMDB.
CSV export of this query is later used for fix of TMDb records using python and Selenium

CE QUE CE SCRIPT CHERCHE : une entite TMDb SANS identifiant Wikidata utilisable,
c'est-a-dire absent, vide, ou present mais mal forme (« Q4157228) », « 116973523 »
sans son Q, mesures dans l'export du 2026-09-03). Remplir, jamais remplacer.

Le cas voisin, l'entite dont l'identifiant est un QID valide mais FAUX, a quitte ce
fichier le 2026-09-05 pour wikidata-id-person-replace.sql. Ecrire par-dessus une valeur
valide detruit de l'information sur un site tiers, et demande une preuve que remplir
une case vide ne demande pas : les deux ne peuvent pas partager le meme fichier ni le
meme passage du robot.

Les deux cas etaient relies par ET jusqu'au 2026-09-01, ce qui rendait le premier
inatteignable des que l'identifiant valait NULL, NULL <> 'Q123' valant NULL et non
vrai. Corrige en OU le 2026-09-01, puis separe en deux fichiers le 2026-09-05.

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
/* ⚠ GARDE 2 : CE FICHIER NE REMPLIT QUE LES CASES VIDES OU ILLISIBLES.
   Mesure du 2026-09-01 : 20 201 lignes remplissent une case VIDE, 751 remplaceraient
   un QID valide mais different. Les deux n'ont pas le meme risque, le premier
   n'ajoute que de l'information, le second en detruit, sur un site tiers et par un
   robot qui ne relit rien.

   NE PAS RETIRER CETTE LIGNE POUR RECUPERER LES REMPLACEMENTS. Ils vivent depuis le
   2026-09-05 dans wikidata-id-person-replace.sql, qui applique en plus un garde 3 :
   n'exporter un remplacement que si le QID candidat designe lui-meme cette fiche TMDb
   en P4985. Mesure du 2026-09-05 sur les films, sur 752 remplacements possibles,
   659 sont ainsi corrobores, 73 sans preuve et 20 contredits par Wikidata. Retirer la
   ligne ci-dessous ferait entrer ces 93 la sans le moindre garde-fou.

   Les deux populations sont disjointes par construction, leur reunion est celle que
   la requete d'origine visait. */
AND (P1.ID_WIKIDATA IS NULL OR P1.ID_WIKIDATA = '' OR P1.ID_WIKIDATA NOT REGEXP '^Q[0-9]+$')
/* ⚠ GARDE 4 : NE DEPLACER UN QID DEJA POSE QUE SI WIKIDATA DESIGNE CETTE FICHE.
   Ajoute le 2026-10-10 apres une boucle constatee dans les journaux du robot.

   Quand deux fiches TMDb partagent le meme identifiant IMDb (doublons TMDb), ou
   quand une entite Wikidata porte plusieurs P345 (une trilogie, ses trois volets),
   le rapprochement par IMDb designe les deux fiches. Celle qui a le QID sort de ce
   fichier (garde 2), celle qui ne l'a pas y entre, avec l'autre en ID_PERSON_ERASE_WIKIDATA_ID.
   Le robot efface l'une et remplit l'autre ; le lendemain les roles sont inverses
   et l'export propose le chemin retour. Mesure sur les journaux du 2026-09-14 au
   2026-10-10 : 340 fiches basculaient a chaque passage (138 films, 29 series,
   173 personnes), 1 254 ecritures sur 4 285, autant d'editions fictives creditees
   au compte TMDb.

   Remplir une case vide reste permis sans preuve, comme avant. Prendre le QID a une
   autre fiche demande la meme preuve que le remplacement (garde 3 du -replace) :
   le QID lui-meme doit designer cette fiche en P4985. Sinon on laisse le QID ou il
   est. L'etat converge : au plus un deplacement, vers la fiche que Wikidata nomme,
   puis plus rien. Sur les exports du 2026-10-10, ce garde ecarte 31 lignes de
   films sur 81 avec effacement, 16 series sur 30, 79 personnes sur 123.

   ⚠ ET LA FICHE QUI DETIENT LE QID NE DOIT PAS ETRE NOMMEE ELLE AUSSI. Premier jet
   du garde, 2026-10-10 : seule la fiche a remplir etait verifiee. Le test sur le
   VPS le soir meme a laisse passer 18 paires de films dans les deux sens, parce que
   Wikidata y nomme TOUTES les fiches TMDb de l'entite : « Drums of Fu Manchu » porte
   P4947 = 3488 et 3490 (serial et version longue), la trilogie Den-O nomme ses trois
   volets. Les deux fiches etant chacune « prouvees », la boucle continuait. Quand
   Wikidata nomme aussi la fiche qui detient le QID, celle-ci a autant de droit que
   l'autre, et TMDb n'accepte le QID que sur une seule : on le laisse ou il est.

   EXISTS correle et non jointure : il ne s'evalue que pour les lignes qui ont un
   P2, une centaine, et s'appuie sur l'index de ID_WIKIDATA. Comparaison
   numerique voulue, sans CAST (voir AGENTS.md, collation). */
AND ( P2.ID_PERSON IS NULL
      OR ( EXISTS ( SELECT 1
                    FROM T_WC_WIKIDATA_STATEMENT sc
                    INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE corrob ON corrob.ID_STATEMENT = sc.ID_STATEMENT
                    WHERE sc.ID_WIKIDATA = WP.ID_WIKIDATA AND sc.ID_PROPERTY = 'P4985'
                      AND (sc.`RANK` IS NULL OR sc.`RANK` <> 'deprecated')
                      AND corrob.VALUE_EXTERNAL_ID = P1.ID_PERSON )
           AND NOT EXISTS ( SELECT 1
                    FROM T_WC_WIKIDATA_STATEMENT sh
                    INNER JOIN T_WC_WIKIDATA_EXTERNAL_ID_VALUE holder ON holder.ID_STATEMENT = sh.ID_STATEMENT
                    WHERE sh.ID_WIKIDATA = WP.ID_WIKIDATA AND sh.ID_PROPERTY = 'P4985'
                      AND (sh.`RANK` IS NULL OR sh.`RANK` <> 'deprecated')
                      AND holder.VALUE_EXTERNAL_ID = P2.ID_PERSON ) ) )
/* ⚠ LE BLOC « les deux cas cherches, en OU » A ETE RETIRE LE 2026-09-05, et son
   absence vaut d'etre expliquee, faute de quoi quelqu'un le remettra.

   Il testait ( IS NULL OR = '' OR mal forme OR <> WP.ID_WIKIDATA ). Le garde 2
   ci-dessus implique deja ses trois premieres branches, et exclut la quatrieme :
   une valeur qui differe sans etre ni vide ni mal formee est un QID valide, donc
   deja ecartee. Le bloc etait donc entierement mort, mais il se lisait comme si ce
   fichier traitait encore le cas de la valeur fausse. C'est desormais le role de
   wikidata-id-person-replace.sql. */
AND WP.ID_WIKIDATA NOT IN ('Q11473776')
/*
AND P1.ADULT = 0
 */
ORDER BY P1.ID_PERSON ASC
