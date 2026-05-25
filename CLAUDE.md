# SakuraLeveling

Bot Discord RPG en Python 3.12, architecture clean (bot / application / domain / infrastructure), SQLite en local, déploiement VPS via systemd.

## Commandes canoniques

```bash
# Tests domaine (référence — doivent toujours passer)
.venv/bin/python -m pytest tests/domain

# Lancer le bot en local
.venv/bin/python -m app.bot.main

# État Alembic
.venv/bin/alembic current
.venv/bin/alembic heads

# Appliquer migrations
.venv/bin/alembic upgrade head

# Synchroniser sans rejouer le SQL (uniquement si schéma déjà à la cible)
.venv/bin/alembic stamp head

# Seed contenu (mobs, items, classes, crafts, quêtes)
.venv/bin/python -m app.infrastructure.db.seeders.seed_content

# Inspecter la DB
sqlite3 lita_v2.db "SELECT id, code, name FROM mob_definitions;"
sqlite3 lita_v2.db "PRAGMA table_info(mob_definitions);"
sqlite3 lita_v2.db "SELECT * FROM alembic_version;"
```

## Architecture (4 couches)

| Couche | Rôle | Dossier |
|---|---|---|
| **bot** | Discord — cogs, slash commands, vues, embeds, rendering Pillow, runtime d'encounter | `app/bot/` |
| **application** | Use cases + services orchestrateurs (encounter_service) | `app/application/` |
| **domain** | Entities, value objects, services métier purs (combat, stats, regen, classes) | `app/domain/` |
| **infrastructure** | DB (models, repositories, seeders), config, content JSON | `app/infrastructure/` |

Ordre de lecture conseillé avant patch : `pyproject.toml` → `alembic.ini` → dernière migration → `app/infrastructure/config/settings.py` → couche concernée → tests existants → tâche.

## Invariants métier (non négociables)

- **`Player` n'a PAS de `current_hp`**. Les HP courants viennent de `PlayerHealthState` (stockage dédié + service de régénération).
- **`hp_regeneration` est OUT-OF-COMBAT uniquement**. La stat ne s'applique JAMAIS pendant un combat (party / solo / duel) — elle est purement passive entre les combats, appliquée par `HealthRegenerationService` selon le temps écoulé. Ne pas réintroduire `+= hp_regeneration` dans les boucles de combat.
- **`Stats` est le value object canonique** pour toute stat de combat : `max_hp`, `attack`, `defense`, `crit_chance`, `crit_damage`, `dodge`, `hp_regeneration`, `speed`.
- **Conventions des pourcentages** :
  - `crit_chance`, `dodge` : entiers `0..100` (50 = 50%)
  - `crit_damage` : entier, **100 = neutre, 150 = ×1.5** (PAS un float multiplicateur)
- **Snapshots de combat** : `PartyCombatService.players_state` doit contenir toutes les stats pour permettre recalcul du score équipe en cours de combat.
- **Discord interactions longues** : `interaction.response.defer(ephemeral=True)` puis `interaction.followup.send(...)`. Une seule réponse primaire.
- **Images de mobs** : `mob.image_name` (asset local sous `assets/mobs/`), pas de URL externe.
- **Famille de mobs** : champ `family` (snake_case) sur `MobDefinition`. Toujours renseigner pour qu'un mob soit comptabilisé dans les classements de famille (ex : "gobelin" pour tous les gobelins).
- **Tracking des kills** : table `player_mob_kills` (player_id, mob_code, kill_count). Incrémentée dans `EncounterService.apply_rewards` (combat de groupe) et `FightMobUseCase` (combat solo) pour chaque survivant après victoire.
- **Répartition des récompenses (combat de groupe)** — V2 équilibrage :
  - **Or** : pool **FIXE** = `mob.gold_reward` (PLUS ×survivants), réparti entre survivants selon le **score de contribution multi-métriques** (dégâts infligés, dégâts tankés, PV soignés actifs). Pool fixe ⇒ l'or/heure d'un groupe ≈ celui d'un solo (on tue plus vite mais chacun touche une part plus petite) → **l'or est le régulateur de l'éco** : les power-levelés co-op montent vite en XP mais manquent d'or → sous-équipés → gatés par la difficulté. Mort en combat ⇒ 0 or. `hp_healed` = soins actifs uniquement (pas la régen passive).
  - **XP** : montant plein **ÉGAL pour tous**, aucune variance de puissance, **morts INCLUS** (le mort gagne l'XP + level-up mais ni or ni loot ni kill). En co-op, l'XP totale créée est ×taille du groupe (récompense sociale assumée, pas de cap de joueurs). `RewardDistributionService.distribute_xp(mob_xp_reward, contributions)`.
  - **Drops** : roll indépendant via `LootService` pour chaque survivant ; **drop commun de famille** (via `family_drops.json` + `family_drop_loader`) avec quantité ∝ puissance du mob.
  - **Kill counter** : tous les survivants reçoivent +1 (pas les morts).
  - Le `PlayerReward.contribution_share` (0..1) expose la part calculée pour affichage et debug.
- **Métriques de combat** trackées par `PartyCombatService` dans `PlayerContribution` : `damage_dealt`, `damage_tanked`, `hp_healed` (heal actif uniquement, pas la régen), `survived`, `final_hp`.
- **Affichage du résultat** : deux messages distincts pendant un encounter naturel.
  - **Message de spawn** : reçoit le `BattleSummaryView` à la fin (paginé 2 pages : Récompenses ↔ Détails). La page Détails affiche en tête un graphique ASCII de la **part de victoire** (médailles 🥇🥈🥉 pour le top 3, barre de progression `████░░` proportionnelle à `contribution_share`). Helper `_build_contribution_chart` dans [`battle_summary_embeds.py`](app/bot/embeds/battle_summary_embeds.py).
  - **Message de journal** : envoyé au début du combat, édité à chaque tour avec la ligne d'action (qui frappe qui, dégâts, crit, esquive) + PV courants. À la fin du combat, ajoute en tête un lien `jump_url` vers le message de spawn (où sont les récompenses). Cf. [encounter_combat_log_embed.py](app/bot/embeds/encounter_combat_log_embed.py).
- **Rang du joueur** : dérivé du `power_score` via `PowerScoreService.compute_rank` (paliers stricts F- → SSS+). **V2** : le power score = `offensive × PV_effectifs` où la **défense compte en PV-plats** (`PV + DEF×25`, cohérent avec le combat soustractif — PAS en %) et le crit en espérance corrigée (`crit_chance × (crit_damage−100)`). Seuils recalibrés sur la courbe du joueur de référence : **niveau ~100 = rang S**, SS-/SSS+ = tail infini. Pas persisté — toujours recalculé.
- **V2 — stats & progression** (équilibrage refondu) :
  - **Combat SOUSTRACTIF** : `dégâts = max(1, ATK_crité − DEF)`, crit AVANT défense (perce l'armure), **sans cap** sur crit_damage. Parité voulue : 1 ATK = 1 DEF. Mob DEF ne doit jamais approcher l'ATK joueur (anti-plancher ; Blindé capé à 70% ATK joueur).
  - **Aucune stat au level-up** : `StatsService` base CONSTANTE (100 PV / 10 ATK / 5 DEF). Le niveau ne donne qu'**1 point de compétence**. Toute la croissance vient de l'**arbre** + gear/classe/titres.
  - **Arbre = moteur de stats** : nœuds **plats** (`atk_flat`/`def_flat`/`hp_max_flat`) = moteur infini non plafonné ; nœuds **%** plafonnés dans `aggregate_bonuses` (atk/def/hp ≤ +200%, gold/xp ≤ +100%, drop ×2). 3 branches (Attaque/Défense/Utilitaire), chaîne stricte, anneaux 5 simples + 1 spécial. Généré par `scripts/generate_skill_tree.py` (extensible en ajoutant des anneaux).
  - **Mobs** : stats relatives au joueur de référence (`scripts/restat_mobs.py`) — DEF mob ≈ 45% ATK joueur, PV ≈ 11× ATK joueur (~20 coups), XP/kill = 6.25·L, or/kill = 3·L. Archétypes standard/brute/blindé/rapide.
  - **Courbe d'XP** : `XP_pour_next = 50·L^1.5` → kills/niveau `= 8·√L` (~3-4 mois solo pour le niveau 100). Géré par `ProgressionService`.
  - **À faire plus tard** : gear tiéré sur les 27 paliers + coûts craft/forge en or (le craft est aujourd'hui un sink de MATÉRIAUX uniquement, pas d'or).

## Workflow Git

Dev se fait sur `main`. Pour pousser en staging beta (déployée sur VPS) :

```bash
git checkout beta
git merge main
git push origin beta
git checkout main
```

## Slash commands disponibles

| Commande | Cog | Rôle |
|---|---|---|
| `/profile [target]`, `/equipement [target]`, `/equipement_list [target]`, `/inventory [target]`, `/class [target]`, `/gold [target]` | `player_cog` | Consultatives — `target` optionnel : par défaut soi-même, sinon profil d'un autre joueur |
| `/equip`, `/unequip <slot>`, `/class_set`, `/classes`, `/daily`, `/gather`, `/craft`, `/craft_list`, `/forge`, `/forge_list` | `player_cog` | Actions sur soi ou listes globales (`/daily` reset à minuit UTC) |
| `/fight @target` | `player_cog` | Duel 1v1 PvP entre joueurs (rien à gagner ni à perdre, juste pour le ladder) |
| (boucle automatique) | `encounter_cog` | Spawn d'encounters, recrutement, combat de groupe |
| `/top <category>` | `leaderboard_cog` | Classements (puissance, niveau, or, stats, kills total/mob/famille, duels 1v1) avec autocomplete |
| `/admin give_gold`, `/admin set_gold`, `/admin give_xp`, `/admin set_level`, `/admin give_item`, `/admin remove_item` | `admin_cog` | **Admin uniquement** — tous prennent `target: discord.Member` |
| `/admin give_skill_points` (+/-), `/admin set_skill_points` | `admin_cog` | **Admin uniquement** — gestion directe des skill points |
| `/admin set_current_hp`, `/admin heal_full` | `admin_cog` | **Admin uniquement** — manipulation des PV courants |
| `/admin set_daily_streak`, `/admin set_class`, `/admin set_kills` | `admin_cog` | **Admin uniquement** — set arbitraire (avec autocomplete sur class/mob) |
| `/admin force_equip`, `/admin force_unequip` | `admin_cog` | **Admin uniquement** — bypass des checks d'équipement (slot canonique par défaut) |
| `/admin set_duel_rank` | `admin_cog` | **Admin uniquement** — force la position du joueur dans le ladder 1v1 (décale les autres) |
| `/admin reset_player @target` | `admin_cog` | **Admin uniquement** — réinitialise tout sauf l'identité Discord |
| `/admin spawn_encounter [mob_code]` | `admin_cog` | **Admin uniquement** — spawn immédiat d'un encounter (random ou mob spécifique) |
| `/admin end_encounter` | `admin_cog` | **Admin uniquement** — annule l'encounter actif |
| `/admin shop_add`, `/admin shop_set`, `/admin shop_remove`, `/admin shop_set_stock` | `admin_cog` | **Admin uniquement** — gestion du shop (autocomplete sur item_code) |
| (webapp) `/admin` | webapp | **Admin uniquement** — interface web pour CRUD items/mobs (OAuth Discord, port 8001). Voir section Skill Tree pour détails. |
| `/shop`, `/buy <item> <qty>`, `/sell <item> <qty>` | `shop_cog` | Shop joueur paginé par catégorie (achat prix fixe, vente prix dynamique selon saturation) |
| `/skill [target]` | `skill_cog` | Arbre de compétences avec image, boutons Investir/Vue web/Reset (cooldown 7j) |
| `/use <item_code>` | `player_cog` | Utiliser un consommable (potions de soin I/II/III en V1) |
| `/help [command]` | `help_cog` | Liste dynamique des commandes (autocomplete) ou détail d'une commande |
| `/title [target]`, `/title_set [code]` | `title_cog` | Voir / activer un titre (cosmétique) — effets passifs toujours actifs |
| `/panoplie <nom>` | `panoplie_cog` | Détail d'une panoplie : paliers, bonus, pièces qui la composent (autocomplete sur les familles) |
| `/equip_panoplie <nom>` | `player_cog` | Équipe en 1 clic toute une panoplie 12/12. Refuse si pondéré < 12 (les armes 2-mains comptent pour 2). Conserve les pièces de la bonne famille déjà équipées. |
| `/craft_panoplie <nom>`, `/forge_panoplie <nom>` | `player_cog` | Bulk-craft des pièces de panoplie manquantes (filtré par station forge/craft). Preview avec ingrédients utilisés + boutons Confirmer/Annuler. Liste les manquants si ressources insuffisantes. |
| `/create_set <nom>`, `/delete_set <nom>`, `/equip_set <nom>` | `player_cog` | Loadouts personnels : sauvegarde l'équipement actuel sous un nom libre, supprime, ou rappelle un set. Tables `player_equipment_sets` + `player_equipment_set_items`. Refuse à l'equip si une pièce du set n'est plus possédée. |
| `/unequip <slot\|all>` | `player_cog` | `slot=all` retire tout l'équipement d'un coup. |
| `/weekly`, `/weekly_claim <code>` | `weekly_quest_cog` | 3 quêtes hebdo random tirées le lundi UTC |
| `/brocante list/my/sell/buy/cancel` | `brocante_cog` | Marketplace P2P avec commission shop (5%) |
| `/boss spawn <boss_code>`, `/boss list`, `/boss stop` | `world_boss_cog` | Spawn manuel admin / catalogue + auto-spawn hebdo. `stop` arrête le boss actif sans distribuer de récompenses (cleanup/debug). |

## Système d'administration

- **Admins** : Discord IDs listés dans `.env` via `ADMIN_DISCORD_IDS=id1,id2,...` (parsé en liste par `Settings.admin_ids`).
- **Décorateur** `@admin_only` (dans `app/bot/checks/admin_check.py`) à apposer sur toute commande sensible.
- **Targeting** : les commandes consultatives acceptent `target: discord.Member | None`. Quand `target=None` → auto-create du profil de l'auteur. Quand `target` est spécifié → lookup pur, message d'erreur si profil inexistant. Helper : `PlayerCog._resolve_profile`.
- Le cog `AdminCog` n'a **pas** de restriction de canal (`interaction_check`) — admin peut agir depuis n'importe où.

## Pattern `interaction_check` par cog

Convention : la restriction au canal beta est **par cog** via `interaction_check`. Les cogs joueurs la posent ; les cogs spéciaux s'en passent et gatent au niveau de chaque commande.

| Cog | `interaction_check` ? | Stratégie additionnelle |
|---|---|---|
| `player_cog` | ✅ canal beta | — (toutes les commandes joueur) |
| `encounter_cog` | n/a (boucle, pas de slash) | — |
| `leaderboard_cog` | ❌ accessible partout | Lecture publique, pas de restriction |
| `shop_cog` | ✅ canal beta | — |
| `skill_cog` | ✅ canal beta | Boutons grisés si viewer ≠ owner |
| `admin_cog` | ❌ accessible partout | `@admin_only` sur chaque commande |

Pour un nouveau cog : si les commandes restent dans le canal beta → poser `interaction_check`. Si admin / lecture publique → s'en passer et utiliser des décorateurs au niveau commande.

## Helpers partagés

- `app/shared/formatters.py` : `format_int(value)` — séparateurs d'espaces FR (1500 → "1 500"). Utilisé partout (embeds + use cases). Centralisé pour éviter la duplication.

## Système d'équipement et de craft

- **12 slots** définis dans `EquipmentSlot` (`app/shared/enums.py`) :
  - **Principaux** : `casque`, `plastron`, `jambieres`, `bottes`, `main_droite`, `main_gauche` (constante `PRIMARY_SLOTS`)
  - **Secondaires** : `collier`, `bracelet`, `bague`, `ceinture`, `cape`, `boucle_oreille` (constante `SECONDARY_SLOTS`)
- **Item fields** (sur `ItemDefinition`) :
  - `equipment_slot: str | None` — slot canonique où l'item s'équipe ; `None` = item non équipable (ressource).
  - `requires_two_hands: bool` — vrai pour les armes 2-mains qui occupent main_droite ET main_gauche.
  - `family: str` — famille de panoplie ("iron", "slime", "gobelin", "leather", "linen"). Vide = item hors panoplie. Sert au calcul des bonus de set.
- **Convention armes 1-main** : `equipment_slot="main_droite"` ; le `EquipItemUseCase` accepte aussi `main_gauche` pour l'ambidextrie. Refuse de placer la même instance dans les deux mains (besoin de 2 exemplaires distincts).
- **Convention armes 2-mains** : stockées en `main_droite` en DB, mais `OFF_HAND` est verrouillée tant qu'une 2-mains est portée. Équiper en `main_gauche` déséquipe la 2-mains.
- **Anti-power-creep** : on ne gagne pas de stats au craft, uniquement à l'équipement (libre de changer). Bonus de stats des items volontairement modestes.
- **Commandes** :
  - `/craft_list` : recettes d'équipement / accessoires (hors armes)
  - `/forge_list` : recettes d'armes / boucliers
  - `/craft <recipe>` : fabrique un équipement (refuse les armes)
  - `/forge <recipe>` : forge une arme (refuse les autres)
  - `/equip <item> [slot]` : `slot` optionnel, défaut = slot canonique de l'item
  - `/equipement [target]` : 3 pages **rendues en image PNG** (Pillow) — Principaux (3×2 grid de cards), Secondaires (idem), Résumé (stats totales apportées par l'équipement + bonus de panoplies actifs avec progression). Cf. [`equipment_image.py`](app/bot/rendering/equipment_image.py). Slot vide → marqueur "VIDE", item sans image dans `assets/items/<code>.png` → placeholder avec emoji du slot, slot off_hand verrouillé par 2-mains → "🔒 ARME À 2 MAINS".

## Système de panoplies (set bonuses)

- **Définitions** : [`sets.json`](app/infrastructure/content/sets.json) — 5 familles avec 4 paliers (2/4/8/12 pièces). Chaque famille = un thème (iron=def, leather=dodge, slime=régen, gobelin=crit chance, linen=crit dmg). Bonus du palier le plus haut REMPLACE celui des paliers inférieurs (pas cumulatif).
- **Catalogue par famille** (16 items distincts pour 12 slots actifs au max) : 4 armures + 6 accessoires + 2 armes légères 1H + 1 arme lourde 2H + 2 boucliers légers 1H + 1 bouclier lourd 2H. Chaque arme/bouclier peut s'équiper en `main_droite` OU `main_gauche` (pas de restriction par catégorie). Une 2-mains occupe main_droite + verrouille main_gauche.
- **Items lourds** : recette = 3× le coût d'un item léger correspondant. Stats positives ≈ 3× les stats léger + malus négatif équivalent aux stats du contre-type léger (arme lourde a une perte def, bouclier lourd a une perte atk). Stats finales clampées à 0 minimum dans `StatsService.calculate_player_stats` (7e étage).
- **Migration `277fe14515ad_add_family_to_item_definitions`** : ajoute la colonne `family` sur `item_definitions`. Il faut donc passer `alembic upgrade head` après le déploiement.
- **Service** : [`SetBonusService.aggregate(equipped_items)`](app/domain/services/set_bonus_service.py) compte les pièces par famille avec ces règles :
  - Slots non-main : 1 item équipé = 1 point
  - Slots main_droite/main_gauche : on compte les `item_definition_id` UNIQUES → 2 mêmes armes = 1 point, 2 différentes = 2 points
  - Une 2-mains (arme ou bouclier) vaut 2 points : 1 pour l'item + 1 pour le slot virtuellement verrouillé
  Sélectionne le palier max atteint, retourne un `SetBonuses` (flat additif sur défense, dodge, crit_chance, crit_damage, hp_regeneration, attack, speed, max_hp). Garde un `active_sets: list[ActiveSetBonus]` pour l'affichage `/equipement` page 3.
- **Equip groupé** : [`EquipPanoplieUseCase`](app/application/use_cases/equip_panoplie.py) — `/equip_panoplie <nom> [option]` valide 12/12 pondéré (2-mains = 2), construit un plan slot→item (priorité aux pièces déjà équipées de la bonne famille), déséquipe le hors-famille, équipe la cible. Param `option` (defaut, double_armes, double_boucliers, arme_lourde, bouclier_lourd) sélectionne la config des mains. Si une 2-mains est dans le plan, `main_gauche` reste vide.
- **Helper** : [`resolve_set_bonuses(equipped_items)`](app/application/services/set_bonus_resolver.py) — wrap simple à appeler partout où on calcule des stats.
- **Wired dans `StatsService`** : 6e étage (après skill bonuses, après title bonuses, après les caps). Permet aux bonus de set de pousser légèrement au-delà des caps standards. Wired aussi dans tous les call sites : `/profile`, encounter (register + resolve), fight_mob (solo), challenge_player (duel), use_consumable, world_boss, get_player_stats, get_leaderboard, admin_cog (force_hp / heal_full), player_cog (preview /equip).
- **Pour ajouter une nouvelle panoplie** : ajouter une entrée dans `sets.json` + tagger les items concernés avec leur `family` dans `items.json`. Pas de code à toucher.

## Système de trade entre joueurs

- **Modèle DB** : tables `trades` (initiator/target_player_id, status, or offerts, expires_at) et `trade_items` (offered_by initiator/target, item_definition_id, quantity).
- **Statuts** : `pending`, `accepted`, `refused`, `cancelled`, `expired`, `failed` (ressources manquantes à l'accept).
- **Sécurité atomique** : `AcceptTradeUseCase` revérifie les ressources des **deux** joueurs au moment de l'acceptation, pas seulement à la proposition. Si l'un manque de quoi que ce soit → status `failed`, aucun déplacement.
- **TTL** : 5 minutes par défaut. Au-delà, status devient `expired` à la prochaine tentative d'acceptation OU à la prochaine itération du cleanup loop côté bot (`TradeCog.expire_loop`, `tasks.loop(minutes=1)` qui appelle `TradeRepository.expire_overdue_pending` — bulk UPDATE WHERE status=pending AND expires_at < now). Idempotent.
- **Un trade pending par paire** : si Alice→Bob a un trade pending, ni Alice→Bob ni Bob→Alice ne peuvent en proposer un nouveau. Annuler ou attendre l'expiration (le cleanup loop libère automatiquement après 5 min).
- **UI** : `/trade @target` → brouillon ephemeral itératif ([`TradeDraftView`](app/bot/views/trade_draft_view.py)) avec 7 boutons. Pas de saisie manuelle de codes : Select Menus listant l'inventaire de l'initiateur ou de la cible (top 25 par quantité), puis modal de quantité. Boutons gold ouvrent une modal mono-champ. Sur Submit → trade créé + message public avec embed + `TradeResponseView` (Accept/Refuse/Cancel) dans [`trade_view.py`](app/bot/views/trade_view.py).

## Système de shop

- **Modèle** : table `shop_items` (item_definition_id unique, buy_price, max_sell_price, min_sell_price, stock_threshold, current_stock, enabled).
- **Achat** (joueur → shop) : prix fixe `buy_price`, stock illimité côté shop (l'admin alimente). Pas d'effet sur `current_stock`.
- **Vente** (joueur → shop) : prix dynamique entre `max_sell_price` (stock vide) et `min_sell_price` (stock ≥ `stock_threshold`), interpolation linéaire. Le `total_sell_amount` simule la dégradation par unité (vendre 1000 d'un coup ne donne pas 1000 × prix max).
- **Drop dégressif** : chaque vente incrémente `current_stock` ; admin peut reset manuellement via `/admin shop_set_stock`.
- **Service** : `ShopPricingService` (domain) calcule `current_sell_price` et `total_sell_amount`. **Use cases** : `BuyFromShopUseCase`, `SellToShopUseCase` (application).

## Système d'arbre de compétences

- **Définition** : un seul JSON [`app/infrastructure/content/skill_tree.json`](app/infrastructure/content/skill_tree.json), 20 nœuds par défaut, chargé au boot par [`skill_tree_loader.py`](app/infrastructure/skill_tree/skill_tree_loader.py) (cache module-level).
- **Modèle DB** : table `player_skill_allocations(player_id, skill_code, level)` 1:N. Cooldown reset 7j via `player_cooldowns` action_key="skill_tree_reset".
- **Convention `values`** : valeurs **cumulatives** au niveau N (lvl 1 → values[0]). Les `costs` restent des deltas (chaque niveau a son coût).
- **Bonus injectés** : `StatsService` accepte un `skill_bonuses: SkillBonuses | None` (4e étage, après équipement/classe, avant les caps). `LootService.generate_loot` accepte un `drop_rate_multiplier`. `EncounterService.apply_rewards` et `FightMobUseCase` chargent les bonus du joueur (xp/gold/drop) avant d'appliquer les récompenses.
- **L'or `/admin give_gold` n'incrémente pas `gold_earned_total`** (career stats), idem les bonus de l'arbre **ne s'appliquent pas** sur l'or admin (pas de double-comptage artificiel).
- **Reset** : `ResetSkillTreeUseCase` (cooldown 7j) restitue tous les points dépensés via `compute_total_refund`. `/admin reset_player` purge aussi les allocations + cooldown.
- **Webapp** : FastAPI mono-service ([`webapp/`](webapp/)), même rendu SVG que le bot. `python -m webapp.main` → http://localhost:8001 (configurable via `WEBAPP_PORT`). Routes :
  - `/skill/<discord_id>` (HTML interactif zoom/pan/hover) + `/api/skill/<discord_id>` (JSON). Le tooltip affiche désormais le **coût du prochain niveau** et la liste des **prérequis** avec leur état (✅ rempli / ❌ manquant). Côté SVG, les arêtes parent → enfant deviennent rouges quand le parent n'est pas encore investi (signal visuel pour guider le joueur vers ce qu'il faut débloquer en premier).
  - `/bestiary` (HTML public, vitrine du jeu) + `/api/bestiary` (JSON). Liste tous les mobs avec stats / drops / power score / rang calculé.
  - `/admin/*` (interface admin protégée par OAuth Discord). Routers dans [`webapp/admin/routers/`](webapp/admin/routers/) — `auth_router` (login/callback/logout), `dashboard_router` (home + 10 stubs), `items_router` et `mobs_router` (CRUD, V1 sans DELETE). Auth : session signée via `itsdangerous` (cookie `sakura_admin_session`, 7j). Vérifie `discord_id ∈ settings.admin_ids`. Templates Jinja2 dans [`webapp/templates/admin/`](webapp/templates/admin/), CSS Sakura pastel rose/violet avec dark mode (toggle Alpine.js stocké en `localStorage`).
  - **Config OAuth** ([`settings.py`](app/infrastructure/config/settings.py)) : `discord_client_id`, `discord_client_secret`, `oauth_redirect_uri`, `admin_session_secret`. À ajouter dans `.env` du VPS + déclarer le redirect URI exact dans Discord Developer Portal (OAuth2 → Redirects). En cas de rotation du secret, redéployer.
  - **Ordre de montage** des routers dans [`webapp/main.py`](webapp/main.py) : `auth_router` → `items_router` → `mobs_router` → `dashboard_router`. Le dashboard router a un catch-all `/admin/{slug}` pour les stubs, qui doit rester en dernier pour ne pas masquer les vraies sous-routes.
- **Bannière `/profile`** ([`profile_banner.py`](app/bot/rendering/profile_banner.py)) : Pillow génère un PNG 1024×880 contenant TOUT le profil. L'embed Discord ne contient que `set_image(attachment://...)` — pas de fields, pas de duplication.
  - **Header** : avatar circulaire, titre (or), nom, niveau · classe, barre XP avec dégradé bleu→cyan, ligne d'infos auto-wrappée sur 2 lignes (or, daily streak, duel #N (W-L), skill points). Badge de rang **avec PWR à l'intérieur** (la lettre F-/SSS+ + `PWR X.XK` en petit dessous, le tout dans un disque coloré selon la lettre).
  - **Cards** : barre verticale d'accent colorée à gauche de chaque carte, couleur dépendant du type de stat (rouge HP, orange ATK, bleu DEF, cyan vitesse, jaune crit, magenta cdmg, vert régen…). 8 stats de combat (PV, Atk, Def, Vit, Crit chance, Crit dégâts, Esquive, Régen) + 8 stats de carrière (Tués, Combats avec %W, Or amassé, Dégâts inf/encaissés, PV soignés, Esquives totales, V/D).
  - **Emojis couleur** via [`emoji_text.py`](app/bot/rendering/emoji_text.py) : helper `draw_text_with_emojis` qui segmente texte+emoji et rend chaque segment avec sa font (DejaVuSans pour le texte, NotoColorEmoji pour les emojis). NotoColorEmoji a une taille native fixe (109 px) qu'on redimensionne. Cache LRU sur les rendus d'emoji. Fallback texte brut si la font emoji est absente.
  - **Dépendance VPS** : `fonts-noto-color-emoji` doit être installé (auto via `scripts/deploy_vps.sh` étape 0 si absent). Sans la font, les emojis tombent en boîtes vides — le fallback ne crash pas mais c'est moche.
  - **Fallback** : si la génération échoue (Pillow plante, font manquante critique), retombe sur `build_player_profile_embed` (ancien embed avec fields). Pas de régression.
  - Fichiers stockés dans `assets/generated_profiles/` (gitignoré).
- **Rendu PNG Discord** : SVG → PNG via cairosvg, pas de Chromium ni Playwright.

## Système de consommables

- **Convention** : `category="consumable"` + `stat_bonuses_json={"effect": str, "value": ...}`. V1 supporte uniquement `effect="heal_percent"` (heal X% du max_hp courant, capé à max_hp).
- **3 potions de soin** (I=50%, II=75%, III=100%) seedées dans [`items.json`](app/infrastructure/content/items.json) et [`shop_items.json`](app/infrastructure/content/shop_items.json).
- **Use case** : [`UseConsumableUseCase`](app/application/use_cases/use_consumable.py) — décrément atomique de l'inventaire, calcul du `max_hp` via `StatsService` (équipement + classe + skill bonuses), update `player_health_state`.
- **Commande** : `/use <item_code>` avec autocomplete sur les consommables actuellement possédés. Refus si pas en inventaire ou si l'item n'est pas marqué consommable.

## Système de world boss

- **Définitions JSON** : [`app/infrastructure/content/boss_definitions.json`](app/infrastructure/content/boss_definitions.json) — 5 bosses progressifs (intro → endgame) avec stats, modifiers, lore. Loader à cache module-level [`boss_definition_loader.py`](app/infrastructure/world_boss/boss_definition_loader.py) (pattern identique à `skill_tree_loader`).
- **Modèle DB** : tables `world_bosses` (1 seul "active" à la fois — instance courante du boss) et `world_boss_participations` (UNIQUE sur boss_id+player_id, cumule damage_dealt/tanked/hp_healed/fights_count). Les définitions vivent dans le JSON, les **instances** vivent en DB.
- **Spawn manuel** : `/boss spawn <boss_code>` (admin) lit la `BossDefinition` depuis le JSON et crée l'instance avec ses stats raw. Refuse s'il y a déjà un boss actif.
- **Auto-spawn** : `WorldBossCog.auto_spawn_loop` (`tasks.loop(hours=1)`) appelle `SpawnRandomWorldBossUseCase`. Conditions de spawn : pas de boss actif + (jamais spawné OU dernière défaite > 7j) + tirage random 5%/heure. Sélection pondérée par `spawn_weight`.
- **Channel dédié** : `settings.boss_channel_id` (fallback `encounter_channel_id` si non défini, pour ne pas casser les .env existants).
- **View** : 3 boutons sur le message du boss (Rejoindre / Quitter / Lancer le combat). Le message est édité après chaque action via `WorldBossCog.refresh_boss_message`.
- **Cooldown 1 combat / jour / joueur** : action_key="world_boss_fight" dans `player_cooldowns`, reset à minuit UTC.
- **Bonus d'équipe** : `WorldBossScalingService` applique +5% par participant additionnel (capé à +50%) sur attack/defense/max_hp du joueur. Speed/crit/dodge ne sont PAS boostés (stats tactiques).
- **Modifiers** ([`BossModifierService`](app/domain/services/boss_modifier_service.py)) — appliqués pendant le combat :
  - `damage_immunity_threshold` (int) : ignore les dégâts < N. Filtré sur le total infligé en V1.
  - `enrage_below_pct` + `enrage_attack_multiplier` : si current_hp/max_hp ≤ X%, multiplie l'attack du boss
  - `crit_immunity` (bool) : neutralise la crit_chance du joueur (les crits = dmg normaux)
  - Modifier inconnu = ignoré poliment → extensibilité par contenu pur
- **Persistence HP** : le boss garde `current_hp` entre les combats. `hp_regeneration=0` forcé — un boss ne regen jamais ses PV.
- **Récompenses** ([`CompleteWorldBossUseCase`](app/application/use_cases/world_boss.py)) : à la défaite, top_damage/top_tank/top_heal reçoivent +200g/+100xp/+1 potion_soin_iii (cumul possible). Tous les participants reçoivent en plus la base : +50g/+25xp/+1 potion_soin_i.
- **Catalogue** : `/boss list` affiche tous les bosses définis avec leurs stats et particularités (utile pour debug/preview).
- **À faire quand le user enverra ses vraies données** : remplacer/étendre `boss_definitions.json`, ajuster `spawn_probability` du loop si besoin.

## Système de titres

- **Définitions** : [`titles.json`](app/infrastructure/content/titles.json) — Slayer (10% dmg vs famille, 100 kills), Champion 1v1, Farmer Fou (exclusifs), Bourreau (500 kills total → +5 crit_damage), Intouchable (100 esquives en encounter → +1 dodge), Taverne Addict (streak 30 → +1 potion_soin_i par /daily), Chasseur Légendaire (1 titre par mob, 50 kills → +5% drop rate sur ce mob).
- **Modèle DB** : `player_titles(player_id, title_code, is_active, unlocked_at)` — 1:N avec unicité applicative (pas en DB) sur `(title_code, *)` pour les titres exclusifs.
- **Tracking dodges** : `player_career_stats.dodges_total` (ajouté par migration `9f6c9ab82525_add_dodges_total_to_player_career_stats`). Incrémenté UNIQUEMENT par `PartyCombatService` quand un joueur esquive (encounters de groupe). Le solo `FightMobUseCase` ne tracke pas les esquives.
- **Effets passifs** ([`title_bonus_service.py`](app/domain/services/title_bonus_service.py)) — agrégés dans `TitleBonuses` :
  - `damage_bonus_vs_family` / `damage_reduction_from_family` : multiplicateurs par famille (titres Slayer)
  - `champion_all_stats_pct` : +X% sur PV/atk/def (multiplicatif, ceil), +X flat sur speed/regen, +X additif sur crit/dodge/crit_dmg. **Appliqué en 5e étage** dans `StatsService.calculate_player_stats` (après les caps standards — un Champion peut donc dépasser le cap crit/dodge de 1 pt).
  - `gold_xp_bonus_pct` : +X% sur or/xp gagnés en combat (Farmer Fou). Appliqué dans `EncounterService.apply_rewards` et `FightMobUseCase` UNIQUEMENT au détenteur — les coéquipiers n'en bénéficient pas.
  - `crit_damage_flat` (Bourreau) / `dodge_flat` (Intouchable) : additifs sur la stat correspondante, appliqués au même 5e étage (s'additionnent au champion_all_stats_pct quand les 2 titres coexistent).
  - `drop_rate_bonus_vs_mob[mob_code]` (Chasseur Légendaire) : multiplicateur drop_rate spécifique à un mob (pas une famille). Appliqué dans `EncounterService.apply_rewards` et `FightMobUseCase` via `LootService(drop_rate_multiplier=base * chasseur_mult)`. Multiplicatif pour préserver la rareté.
  - `daily_bonus_items: list[(item_code, qty)]` (Taverne Addict) : items octroyés à chaque `/daily`. Appliqués dans `ClaimDailyRewardUseCase` après l'or, surfaces dans le `DailyClaimResult.bonus_items` puis dans `build_daily_success_embed`.
- **Helper centralisé** : [`resolve_title_bonuses(session, player_id)`](app/application/services/title_bonus_resolver.py) — charge les codes via `PlayerTitleRepository.list_codes_for_player`, charge les `TitleDefinition` via `title_loader`, agrège via `TitleBonusService`. À appeler partout où on calcule des stats ou des récompenses.
- **Titres exclusifs** ([`exclusive_title_service.py`](app/application/services/exclusive_title_service.py)) :
  - `award_to(title_code, new_holder_id)` : retire à TOUS les autres détenteurs (delete row → l'`is_active` saute aussi) puis assigne au nouveau. Idempotent. La supression de la ligne fait que `get_active_title_code` retombera sur None pour l'ancien détenteur.
  - **Hooks** :
    - Champion 1v1 : à chaque résolution de duel (`ChallengePlayerUseCase`), on lit `duel_rank_repository.list_top(1)` et on appelle `award_to('champion_1v1', top1_id)`.
    - Farmer Fou : à chaque incrément de kill (`EncounterService.apply_rewards` + `FightMobUseCase`), on compare `kill_repository.get_total_kills(candidate)` avec `get_total_kills(current_holder)`. Transfert UNIQUEMENT si candidat > détenteur (égalité ⇒ premier arrivé garde).
- **Hooks d'unlock non-exclusifs** dans `TitleUnlockService` :
  - `check_kills_family(player_id, family)` : déclenché après chaque kill d'un mob dans cette famille.
  - `check_kills_total(player_id)` : déclenché après chaque kill, débloque Bourreau à 500.
  - `check_kills_mob(player_id, mob_code)` : déclenché après chaque kill, débloque le Chasseur Légendaire correspondant.
  - `check_dodges_total(player_id, total)` : déclenché après combat encounter, débloque Intouchable à 100.
  - `check_daily_streak(player_id, streak)` : déclenché à chaque /daily, débloque Taverne Addict à 30.
- **Reset** : `ResetPlayerUseCase` purge `player_titles` du joueur — un Champion 1v1 reseté perd son titre, qu'il sera réattribué au prochain duel.

## Système de duel 1v1 (PvP)

- **Modèle DB** : table `player_duel_ranks(player_id UNIQUE, rank_position, wins, losses)`. Index sur `rank_position`. Plus petit rank_position = mieux classé. `get_or_create` attribue `max(rank_position) + 1` au nouveau venu.
- **Commande** : `/fight @target` ([`player_cog.py`](app/bot/cogs/player_cog.py)) — anime tour par tour via `interaction.followup.send` puis `message.edit` toutes les ~1.2s, embeds dans [`duel_embeds.py`](app/bot/embeds/duel_embeds.py).
- **Règle d'éligibilité** : challenger.rank_position **STRICTEMENT > ** target.rank_position. Sinon `DuelOutcome(success=False)`. Pas de mode consensuel — l'attaque est unilatérale tant que la règle est respectée.
- **HP** : le `DuelCombatService.fight_player_vs_player` démarre les deux combattants à `max_hp` et ne lit JAMAIS `player_health_state`. Aucune écriture en DB sur les HP réels après le duel — l'animation visible est purement cosmétique.
- **Rien d'autre n'est tracké** : pas d'or, XP, loot, kill_count, career_stats. Seuls `wins`/`losses` du `player_duel_ranks` bougent.
- **Cooldown anti-spam** : 60 s entre 2 défis sortants par challenger (action_key="duel_challenge" dans `player_cooldowns`).
- **Swap** : si challenger gagne → `swap_positions(challenger_id, target_id)` (atomique, via valeur sentinelle pour préparer un futur UNIQUE sur rank_position). Sinon ladder inchangé.
- **Reset** : `/admin reset_player` purge la ligne du ladder (via `PlayerDuelRankModel` ajouté à la liste de DELETE de `ResetPlayerUseCase`).
- **Leaderboard** : catégorie `duel_rank` dans `/top` — bypass `LeaderboardService.rank()` (qui trie DESC) et construit directement les `LeaderboardEntry` depuis `repo.list_top()` (déjà trié ASC). Affiche `#N (WV-DD)`.

## Workflow type pour ajouter une nouvelle stat de combat

1. Ajouter le champ dans `app/domain/value_objects/stats.py`
2. Ajouter dans `app/domain/entities/mob_definition.py`
3. Ajouter dans le modèle SQLAlchemy `app/infrastructure/db/models/mob_model.py`
4. Créer la migration Alembic (`alembic revision --autogenerate -m "..."`)
5. Mettre à jour le mapping dans `app/infrastructure/db/repositories/mob_repository.py`
6. Mettre à jour le seeder `app/infrastructure/db/seeders/seed_content.py` + JSON `app/infrastructure/content/mobs.json`
7. Mettre à jour `combat_service.py`, `party_combat_service.py`, `power_score_service.py` si la stat impacte les calculs
8. Vérifier la propagation dans les snapshots `players_state`
9. Mettre à jour les tests dans `tests/domain/`
10. `pytest tests/domain` puis smoke test sur Discord beta

## Sécurité

- Le token Discord est dans `.env` (gitignored). **Ne jamais le committer ni l'exposer.**
- **Backup** `lita_v2.db` avant toute migration ou seed important.
- **Jamais** `alembic stamp` à l'aveugle — toujours inspecter le schéma réel d'abord (`PRAGMA table_info(...)` + `SELECT * FROM alembic_version`).
- **Jamais** de déploiement prod automatique sans tests qui passent.

## Bugs connus / pièges récurrents

- `AttributeError 'Player' has no attribute 'current_hp'` → utiliser `PlayerHealthState` via `PlayerHealthRepository`.
- Score équipe qui tombe pendant le combat → vérifier que `players_state` contient toutes les stats pour le recalcul.
- `Unknown interaction` → ajouter `defer()` avant les opérations longues.
- Mob affiché en carré gris → `image_name` vide ou asset absent dans `assets/mobs/`.
- `duplicate column name` Alembic → schéma déjà modifié, faire `stamp` après inspection au lieu de `upgrade`.

## Déploiement beta (VPS)

```bash
# Sur ta machine locale
git checkout beta && git merge main && git push origin beta

# Sur le VPS
cd /home/ubuntu/SakuraLeveling
cp lita_v2.db lita_v2_backup_$(date +%Y%m%d_%H%M%S).db
git pull origin beta
.venv/bin/alembic upgrade head    # ou stamp si schéma déjà aligné manuellement
.venv/bin/python -m app.infrastructure.db.seeders.seed_content
sudo systemctl restart sakura-bot
sudo journalctl -u sakura-bot -n 100 --no-pager
```
