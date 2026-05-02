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
- **`Stats` est le value object canonique** pour toute stat de combat : `max_hp`, `attack`, `defense`, `crit_chance`, `crit_damage`, `dodge`, `hp_regeneration`, `speed`.
- **Conventions des pourcentages** :
  - `crit_chance`, `dodge` : entiers `0..100` (50 = 50%)
  - `crit_damage` : entier, **100 = neutre, 150 = ×1.5** (PAS un float multiplicateur)
- **Snapshots de combat** : `PartyCombatService.players_state` doit contenir toutes les stats pour permettre recalcul du score équipe en cours de combat.
- **Discord interactions longues** : `interaction.response.defer(ephemeral=True)` puis `interaction.followup.send(...)`. Une seule réponse primaire.
- **Images de mobs** : `mob.image_name` (asset local sous `assets/mobs/`), pas de URL externe.
- **Famille de mobs** : champ `family` (snake_case) sur `MobDefinition`. Toujours renseigner pour qu'un mob soit comptabilisé dans les classements de famille (ex : "gobelin" pour tous les gobelins).
- **Tracking des kills** : table `player_mob_kills` (player_id, mob_code, kill_count). Incrémentée dans `EncounterService.apply_rewards` (combat de groupe) et `FightMobUseCase` (combat solo) pour chaque survivant après victoire.
- **Répartition des récompenses (combat de groupe)** :
  - **Or** : pool = `mob.gold_reward × nb_survivants`, partagé selon le **score de contribution multi-métriques** (role-agnostic). Pour chaque métrique active dans l'équipe (dégâts infligés, dégâts tankés, PV régénérés), chaque survivant reçoit `sa_part / total_équipe` points. Score final = somme des 3. Un Tank pur, un Healer pur ou un DPS pur gagnent tous 1 point dans leur spécialité ; un polyvalent cumule. Une métrique inutilisée (ex : aucun heal dans le combat) est ignorée.
  - **XP** : multiplier = `clamp(mob_power / player_power, 0.5, 2.5)`, XP = `mob.xp_reward × multiplier`. Joueurs faibles vs mob fort gagnent plus.
  - **Drops** : roll indépendant via `LootService` pour chaque survivant.
  - **Kill counter** : tous les survivants reçoivent +1.
  - Le `PlayerReward.contribution_share` (0..1) expose la part calculée pour affichage et debug.
- **Métriques de combat** trackées par `PartyCombatService` dans `PlayerContribution` : `damage_dealt`, `damage_tanked`, `hp_healed` (régen effective), `survived`, `final_hp`.
- **Affichage du résultat** : `BattleSummaryView` paginée 2 pages (Récompenses ↔ Détails). Construit par `apply_rewards` qui retourne `BattleSummary`.

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
| `/profile [target]`, `/equipment [target]`, `/inventory [target]`, `/class [target]`, `/quests [target]` | `player_cog` | Consultatives — `target` optionnel : par défaut soi-même, sinon profil d'un autre joueur |
| `/equip`, `/class_set`, `/classes`, `/daily`, `/quest_claim`, `/gather`, `/craft`, `/craft_list` | `player_cog` | Actions sur soi ou listes globales |
| `/fight @target` | `player_cog` | Duel 1v1 PvP entre joueurs (rien à gagner ni à perdre, juste pour le ladder) |
| (boucle automatique) | `encounter_cog` | Spawn d'encounters, recrutement, combat de groupe |
| `/top <category>` | `leaderboard_cog` | Classements (puissance, niveau, or, stats, kills total/mob/famille, duels 1v1) avec autocomplete |
| `/admin give_gold`, `/admin set_gold`, `/admin give_xp`, `/admin set_level`, `/admin give_item`, `/admin remove_item` | `admin_cog` | **Admin uniquement** — tous prennent `target: discord.Member` |
| `/admin reset_player @target` | `admin_cog` | **Admin uniquement** — réinitialise tout sauf l'identité Discord |
| `/admin spawn_encounter` | `admin_cog` | **Admin uniquement** — force le spawn immédiat d'un encounter |
| `/admin shop_add`, `/admin shop_set`, `/admin shop_remove`, `/admin shop_set_stock` | `admin_cog` | **Admin uniquement** — gestion du shop (autocomplete sur item_code) |
| `/shop`, `/buy <item> <qty>`, `/sell <item> <qty>` | `shop_cog` | Shop joueur (achat prix fixe, vente prix dynamique selon saturation) |
| `/skill [target]` | `skill_cog` | Arbre de compétences avec image, boutons Investir/Vue web/Reset (cooldown 7j) |

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
- **Convention armes 1-main** : `equipment_slot="main_droite"` ; le `EquipItemUseCase` accepte aussi `main_gauche` pour l'ambidextrie. Refuse de placer la même instance dans les deux mains (besoin de 2 exemplaires distincts).
- **Convention armes 2-mains** : stockées en `main_droite` en DB, mais `OFF_HAND` est verrouillée tant qu'une 2-mains est portée. Équiper en `main_gauche` déséquipe la 2-mains.
- **Anti-power-creep** : on ne gagne pas de stats au craft, uniquement à l'équipement (libre de changer). Bonus de stats des items volontairement modestes.
- **Commandes** :
  - `/craft_list` : recettes d'équipement / accessoires (hors armes)
  - `/forge_list` : recettes d'armes / boucliers
  - `/craft <recipe>` : fabrique un équipement (refuse les armes)
  - `/forge <recipe>` : forge une arme (refuse les autres)
  - `/equip <item> [slot]` : `slot` optionnel, défaut = slot canonique de l'item
  - `/equipment [target]` : 2 pages naviguables (Principaux / Secondaires)

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
- **Webapp** : FastAPI mono-service ([`webapp/`](webapp/)), même rendu SVG que le bot. `python -m webapp.main` → http://localhost:8000. Routes : `/skill/<discord_id>` (HTML interactif zoom/pan/hover) + `/api/skill/<discord_id>` (JSON).
- **Rendu PNG Discord** : SVG → PNG via cairosvg, pas de Chromium ni Playwright.

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
