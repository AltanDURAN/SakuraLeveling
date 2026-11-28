# Bestiaire à découvrir (`/bestiaire monstres|boss`) — 07/11/2026

_Fiche sortie de CLAUDE.md le 28/11/2026 (audit) : texte inchangé, liens recalés._

Demande de l'auteur : silhouette tant que le monstre n'a pas été vaincu, et compteur de victoires. `/bestiaire` est un GROUPE (Discord n'accepte pas une commande qui soit aussi un groupe) : `monstres` et `boss` (ex-`/boss list`, même style). Socle commun `PagedBookView` (◀ n/N ▶ réservé à l'auteur) + `picture` (image ou silhouette).

- **Découvert** = au moins une victoire en COMBAT DE ZONE (`player_mob_kills`, `PlayerKillRepository.get_kills_per_mob` — le même compteur que les titres ; la tour n'y compte pas). Sans profil, rien n'est découvert.
- **Zone pas encore mise en place** (28/11/2026) : un monstre pas encore vaincu d'une famille de `unready_families()` (zone sans décor) a un grand « ? » au lieu de sa silhouette (`picture(..., unready=)`).
- **Pas encore vaincu** ([`bestiaire_view.py`](../../app/bot/views/bestiaire_view.py), `build_unknown_embed`) : « ❔ ??? », sa silhouette en vignette ([`silhouette.py`](../../app/bot/rendering/silhouette.py) : forme remplie de violet presque noir, halo lavande lisible sur les deux thèmes, 256 px, cache par date de l'image, fichier au nom NEUTRE `inconnu.png` — le nom du fichier se lit dans Discord), le salon où le trouver, la mention Élite. Ni nom, ni stats, ni butin — ni FAMILLE (« Slime », « Gobelin »… donneraient son nom).
- **Vaincu** : la fiche complète + « ⚔️ Tes victoires ». Pied de page et menu des familles : « 📖 X/Y découverts ».
- **Boss** ([`boss_bestiary_view.py`](../../app/bot/views/boss_bestiary_view.py)) : découvert = abattu (statut `defeated` ET PV à 0) avec au moins un assaut du joueur (`WorldBossRepository.victories_by_code`, `fights_count > 0`) ; inconnu : silhouette, salon du raid et niveau où il vient ; connu : niveau du raid, « ⚔️ Tes victoires », élément, stats, mécaniques (`mechanics_lines` : phases, ultime, gardes, particularités `TRAIT_LABELS`), butin. Trié par niveau, « 👑 X/5 vaincus ».
- Le bestiaire du SITE (`/bestiary`, vitrine publique) reste complet.
- Tests : [`test_bestiaire_view.py`](../../tests/bot/test_bestiaire_view.py).
