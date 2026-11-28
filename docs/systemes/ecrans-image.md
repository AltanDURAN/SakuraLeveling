# Écrans en image — 20-21/11/2026

_Fiche sortie de CLAUDE.md le 28/11/2026 (audit) : texte inchangé, liens recalés._

Demande de l'auteur : les écrans encore en texte brut prennent la DA du bot (celle de `/affinites`, de la bannière et des PNJ).

- **Couleurs** (21/11/2026, demande de l'auteur : des écrans colorés et cohérents) : UNE couleur par sens, définie dans `ui_kit` et utilisée partout — `GOLD` or et ce qui est à toi, `XP`, `HP` / `ATK` / `DEF` / `MANA` / `SPEED` / `CRIT` / `CRIT_DMG` / `DODGE` / `REGEN` (celles de la bannière), `TIME` attentes, `ITEM` objets, `FIRE` série, `PINK` cartes et cosmétiques, `EARTH` matériaux. Rôles des défis = ATK / DEF / REGEN ; objets colorés par effet (`screens.item_color`). Chaque écran a sa couleur : filet sous le titre (`header(accent=)`) et pied de page (`footer(color=)`). Ne pas recréer une couleur locale pour un sens qui en a déjà une.
- **Briques communes** : [`rendering/ui_kit.py`](../../app/bot/rendering/ui_kit.py) — fond de nuit à pétales (`canvas`), panneaux, cartes teintées, barres lumineuses, pastilles, en-tête, pied ; `fit` / `clip` / `wrap` pour que rien ne déborde (pseudos de 32 caractères, montants à 7 chiffres testés).
- **Écrans** : `/stats` ([`stats_sheet.py`](../../app/bot/rendering/stats_sheet.py)) ; `/quetes` et `/quetes_hebdo` (aussi après « Réclamer »), `/daily`, `/defi` (programme et scores), `/cd`, `/inventaire` (tuiles avec l'image de l'objet, 32 par page au plus) — [`screens.py`](../../app/bot/rendering/screens.py).
- **Règles** : le rendu se fait TOUJOURS dans un thread ; [`screen_embed.image_embed`](../../app/bot/embeds/screen_embed.py) renvoie `None` si Pillow échoue et la commande garde alors son embed texte d'avant (jamais d'écran vide). Les heures de `/cd` sont celles de Paris (une image ne peut pas porter de compte à rebours Discord).
- **Aussi en image (21/11/2026)** : `/or` (`compose_gold`), `/classement` (podium + top 10, ta ligne surlignée — `compose_leaderboard`), résultat d'un essai de défi (`compose_attempt`), `/records` et `/titre` (écran de listes à sections `compose_list` ; `/titre` : 12 lignes par page, `title_image_pages`). Le texte reste en repli partout.
- Tests : [`test_screens.py`](../../tests/bot/test_screens.py), [`test_stats_sheet.py`](../../tests/bot/test_stats_sheet.py).
