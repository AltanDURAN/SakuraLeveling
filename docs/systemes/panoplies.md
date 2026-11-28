# Système de panoplies (saison 1 — par rareté)

_Fiche sortie de CLAUDE.md le 28/11/2026 (audit) : texte inchangé, liens recalés._

Refonte d'octobre 2026 (idée de l'auteur) : plus de familles d'objets, plus de `sets.json`, plus de `/equiper_panoplie` (`EquipPanoplieUseCase`, `PanoplieCraftsUseCase`, `set_loader` et les pages admin des panoplies ont été supprimés). Le champ `family` des items existe encore mais n'est plus lu.

- **Règle** ([`set_bonus_service.py`](../../app/domain/services/set_bonus_service.py)) : paliers `TIERS` à 2 / 4 / 7 pièces (×1 / ×1,5 / ×3 du bonus simple), comptés PAR RARETÉ, en **cumulatif** : une pièce compte pour sa rareté et toutes les raretés en dessous ; chaque rareté atteint son palier, les bonus s'additionnent. ⚠️ Avec des groupes stricts, améliorer une pièce pouvait FAIRE BAISSER le bonus (7 rares → 6 rares + 1 épique) ; le cumulatif l'interdit (test `test_ameliorer_une_piece_ne_fait_jamais_baisser_le_bonus`).
- **Marches** `RARITY_STEP` (1 / 0,5 / 0,5 / 1 / 1 / 1,5) : leur somme cumulée = `PRIMARY_MULTIPLIER` de la rareté ⇒ un set d'une seule rareté vaut bonus simple × rareté × palier (7 légendaires en Attaque : 2 % × 4 × 3 = +24 %).
- **Deux mains = 2 pièces** (voulu : une seule pièce à farmer et fusionner pour deux places).
- **Type unique choisi par le joueur** (`PANOPLIE_TYPES` : attaque / défense / PV en %, chance crit, dégâts crit, esquive, régén à plat ; ni vitesse ni économie), stocké dans `players.panoplie_bonus` (migration `4e7a1c9d2b58`), changé librement par `/panoplie` (menu). `resolve_set_bonuses(equipped, profile.player.panoplie_bonus)` dans tous les calculs de stats. Les % sont des FRACTIONS dans `SetBonuses` (comme l'arbre), `total` est en unité d'affichage.
- **Affichage** : `/panoplie` (embed + menu), page 2 de `/equipement` (une ligne par rareté ayant atteint un palier).
- Le joueur de référence n'inclut PAS encore ce bonus.
