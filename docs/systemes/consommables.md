# Système de consommables

_Fiche sortie de CLAUDE.md le 28/11/2026 (audit) : texte inchangé, liens recalés._

- **Convention** : `category="consumable"` + `stat_bonuses_json={"effect": str, "value": ...}`. Effets : `heal_percent` (X % des PV max, capé), `mana_percent` (X % du mana max, capé), `elixir` (`kind`, `value`, `minutes` — cf. Elna). Toutes les potions viennent d'**Elna** (`/alchimiste`) ; la potion de soin tombe aussi du slime (10 %) et du coffre.
- **Use case** : [`UseConsumableUseCase`](../../app/application/use_cases/use_consumable.py) — décrément atomique de l'inventaire, stats via `resolve_player_stats` (SANS élixir), régénération hors combat écoulée (élixir de récupération compris) comptée AVANT ; potion refusée (non consommée) si PV / mana déjà pleins.
- **Commande** : `/utiliser <item_code>` avec autocomplete sur les consommables actuellement possédés. Refus si pas en inventaire ou si l'item n'est pas marqué consommable.
