# Système de titres

_Fiche sortie de CLAUDE.md le 28/11/2026 (audit) : texte inchangé, liens recalés._

- **Définitions** : [`titles.json`](../../app/infrastructure/content/titles.json) — Slayer / Pourfendeur (10% dmg vs famille, 100 kills — une par famille, toutes zones), titres de la SEMAINE des défis (Fléau +2 % dégâts, Bastion −2 % dégâts reçus, Ange gardien +2 % soins, Champion de la semaine +1 % stats — exclusifs, `condition_type: weekly_role_trial`), Farmer Fou (exclusif), Bourreau (500 kills total → +5 crit_damage), Intouchable (100 esquives en encounter → +1 dodge), titres de série /daily : Habitué (7 j, +1 % or/XP), Taverne Addict (30 j, +3 crit_damage — n'offre plus de potion), Pilier (100 j, +2 % or/XP), Chasseur Légendaire (1 titre par monstre, toutes zones : 50 kills, 25 pour une élite de groupe → +5% drop rate sur ce monstre), titres des RECORDS (Légende / Prodige / Étoile montante, +5 / +3 / +1 % d'or en combat de zone — exclusifs, redistribués chaque nuit, cf. « Records »). Test : chaque famille et chaque monstre a son titre (`test_content_integrity`).
- **Modèle DB** : `player_titles(player_id, title_code, is_active, unlocked_at)` — 1:N avec unicité applicative (pas en DB) sur `(title_code, *)` pour les titres exclusifs.
- **Tracking dodges** : `player_career_stats.dodges_total` (ajouté par migration `9f6c9ab82525_add_dodges_total_to_player_career_stats`). Incrémenté UNIQUEMENT par `PartyCombatService` quand un joueur esquive (encounters de groupe). 
- **Effets passifs** ([`title_bonus_service.py`](../../app/domain/services/title_bonus_service.py)) — agrégés dans `TitleBonuses` :
  - `damage_bonus_vs_family` / `damage_reduction_from_family` : multiplicateurs par famille (titres Slayer)
  - `champion_all_stats_pct` : +X% sur PV/atk/def (multiplicatif, ceil), +X flat sur speed/regen, +X additif sur crit/dodge/crit_dmg. **Appliqué en 5e étage** dans `StatsService.calculate_player_stats` (après les caps standards — un Champion peut donc dépasser le cap crit/dodge de 1 pt).
  - `gold_xp_bonus_pct` : +X% sur or/xp gagnés en combat (Farmer Fou). Appliqué dans `EncounterService.apply_rewards` UNIQUEMENT au détenteur — les coéquipiers n'en bénéficient pas.
  - `crit_damage_flat` (Bourreau) / `dodge_flat` (Intouchable) : additifs sur la stat correspondante, appliqués au même 5e étage (s'additionnent au champion_all_stats_pct quand les 2 titres coexistent).
  - `drop_rate_bonus_vs_mob[mob_code]` (Chasseur Légendaire) : multiplicateur drop_rate spécifique à un mob (pas une famille). Appliqué dans `EncounterService.apply_rewards` via `LootService(drop_rate_multiplier=base * chasseur_mult)`. Multiplicatif pour préserver la rareté.
  - `daily_bonus_items: list[(item_code, qty)]` : objets octroyés à chaque `/daily` (mécanique conservée ; plus aucun titre ne l'utilise depuis que Taverne Addict donne +3 dégâts critiques).
- **Helper centralisé** : [`resolve_title_bonuses(session, player_id)`](../../app/application/services/title_bonus_resolver.py) — charge les codes via `PlayerTitleRepository.list_codes_for_player`, charge les `TitleDefinition` via `title_loader`, agrège via `TitleBonusService`. À appeler partout où on calcule des stats ou des récompenses.
- **Titres exclusifs** ([`exclusive_title_service.py`](../../app/application/services/exclusive_title_service.py)) :
  - `award_to(title_code, new_holder_id)` : retire à TOUS les autres détenteurs (delete row → l'`is_active` saute aussi) puis assigne au nouveau. Idempotent. La supression de la ligne fait que `get_active_title_code` retombera sur None pour l'ancien détenteur.
  - **Hooks** :
    - Titres de la semaine : `role_trials.settle_week` (dimanche 20 h) appelle `award_to(code, 1er)` pour chaque classement, `revoke(code)` si personne n'a joué. Leurs effets de COMBAT (`damage_dealt_pct`, `damage_taken_reduction_pct`, `heal_power_pct` de `TitleBonuses`) passent par `with_title_passives` dans `resolve_party_passives`.
    - Farmer Fou : à chaque incrément de kill (`EncounterService.apply_rewards`), on compare `kill_repository.get_total_kills(candidate)` avec `get_total_kills(current_holder)`. Transfert UNIQUEMENT si candidat > détenteur (égalité ⇒ premier arrivé garde).
- **Hooks d'unlock non-exclusifs** dans `TitleUnlockService` :
  - `check_kills_family(player_id, family)` : déclenché après chaque kill d'un mob dans cette famille.
  - `check_kills_total(player_id)` : déclenché après chaque kill, débloque Bourreau à 500.
  - `check_kills_mob(player_id, mob_code)` : déclenché après chaque kill, débloque le Chasseur Légendaire correspondant.
  - `check_dodges_total(player_id, total)` : déclenché après combat encounter, débloque Intouchable à 100.
  - `check_daily_streak(player_id, streak)` : déclenché à chaque /daily, débloque Taverne Addict à 30.
- **Reset** : `ResetPlayerUseCase` purge `player_titles` du joueur — un détenteur de titre de la semaine reseté le perd (il sera réattribué à la clôture suivante).
