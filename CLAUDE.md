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

# Seed contenu (mobs, items, crafts, quêtes)
.venv/bin/python -m app.infrastructure.db.seeders.seed_content

# Saison : simulation de progression / reset (aperçu sans --confirm)
.venv/bin/python -m scripts.simulate_season
.venv/bin/python -m scripts.season_reset

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
- **`Player` n'a PAS de `current_mana`** (miroir strict du HP). Le mana courant vit dans `PlayerManaState` (table `player_mana_states`, `PlayerManaRepository`). `mana_max` / `mana_regeneration` sont des STATS calculées (base 100/5 + arbre + gear/classe) ; seul le mana courant est persisté.
- **`hp_regeneration` est OUT-OF-COMBAT uniquement**. La stat ne s'applique JAMAIS pendant un combat (groupe / world boss / épreuve / défi) — elle est purement passive entre les combats, appliquée par `HealthRegenerationService` selon le temps écoulé. Ne pas réintroduire `+= hp_regeneration` dans les boucles de combat.
- **`mana_regeneration` est OUT-OF-COMBAT uniquement** (même règle que `hp_regeneration`). `ManaRegenerationService` (calqué sur `HealthRegenerationService`) régénère le mana/minute entre les combats. Le mana ne remonte JAMAIS pendant un combat : en combat c'est une réserve qui se vide.
- **Compétences actives et mana : EN PAUSE** (décision de l'auteur, oct. 2026 : le déclenchement n'est pas encore trouvé). Le moteur existe (`SkillEffectService`, gating mana dans `PartyCombatService`, `PlayerContribution.final_mana`), mais `skill_loadouts_by_player` est TOUJOURS vide : ⚠️ **le mana n'a aujourd'hui aucun effet en jeu**, alors que des cases de l'arbre et des pièces en donnent (cf. audit du 24/10/2026).
- **`Stats` est le value object canonique** pour toute stat de combat : `max_hp`, `attack`, `defense`, `crit_chance`, `crit_damage`, `dodge`, `hp_regeneration`, `speed`, `mana_max`, `mana_regeneration`. ⚠️ Toute reconstruction `Stats(...)` (dans `StatsService` étages 6/7, `title_bonus_service`, `skill_bonuses.apply_to_stats`) doit REPORTER `mana_max`/`mana_regeneration`, sinon les défauts=0 les effacent.
- **Conventions des pourcentages** :
  - `crit_chance`, `dodge` : entiers `0..100` (50 = 50%)
  - `crit_damage` : entier, **100 = neutre, 150 = ×1.5** (PAS un float multiplicateur)
- **Snapshots de combat** : `PartyCombatService.players_state` doit contenir toutes les stats pour permettre recalcul du score équipe en cours de combat.
- **Discord interactions longues** : `interaction.response.defer(ephemeral=True)` puis `interaction.followup.send(...)`. Une seule réponse primaire.
- **Images de mobs** : `mob.image_name` (asset local sous `assets/mobs/`), pas de URL externe.
- **Famille de mobs** : champ `family` (snake_case) sur `MobDefinition`. Toujours renseigner pour qu'un mob soit comptabilisé dans les classements de famille (ex : "gobelin" pour tous les gobelins).
- **K.O.** : on ne rejoint pas un encounter à 0 PV (régénération comprise) — sinon un joueur à terre mourait au premier coup et touchait quand même l'XP pleine des morts. En rejoignant, `EncounterService._danger_note` prévient si le monstre est ≥ 1,2× (« Risqué ») ou ≥ 2× (« Très dangereux ») plus puissant, ou s'il reste < 30 % des PV : une zone couvre une large plage de niveaux et le monstre est tiré sans regarder qui le combattra.
- **Potion** (`UseConsumableUseCase`) : la régénération hors combat écoulée est comptée AVANT le soin (elle était effacée), et la potion est refusée (non consommée) si les PV sont déjà pleins.
- **Tracking des kills** : table `player_mob_kills` (player_id, mob_code, kill_count). Incrémentée dans `EncounterService.apply_rewards` pour chaque survivant après victoire (il n'y a pas de combat solo dédié).
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
- **Rang du joueur** : dérivé du `power_score` via `PowerScoreService.compute_rank` (paliers stricts **F- → Ω**). **V2** : le power score = `offensive × PV_effectifs` où la **défense compte en PV-plats** (`PV + DEF×25`, cohérent avec le combat soustractif — PAS en %) et le crit en espérance corrigée (`crit_chance × (crit_damage−100)`). Seuils (25/10/2026) calés sur la puissance d'un joueur TYPIQUE — médiane des 4 profils de `scripts/reference_roles.py`, `typical_power` — : un sous-rang tous les 5 niveaux, **niveau 100 typique = rang S**, S+/SS/SSS = au-delà (rapports de l'ancienne table), **Ω** au-delà de SSS+ ; régénérés par `python -m scripts.calibrate_power_ranks --write` (avant, calés sur le joueur de référence sans classes : un joueur investi affichait S+ dès le niveau 70). Le kit de SOUTIEN compte : `calculate_from_stats(stats, passives)` × `HEALER_POWER_FACTOR` (1,45) avec le sort de soin — sans lui, un Soigneur plafonnait à 0,67× un DPS et n'atteignait jamais SS/SSS ; puissance d'un JOUEUR = `resolve_player_power` (profil, épreuve, classement, admin). Pas persisté — toujours recalculé. Mapping tiers (admin) : F=Fer, E=Bronze, D=Argent, C=Or, B=Platine, A=Émeraude, S=Diamant, SS=Master, SSS=Grand Master, Ω=Challenger.
- **SAISON 1 — stats & progression** (refonte d'octobre 2026, REMPLACE le V2 ci-dessous) :
  - **Trois stats de BASE** (`BaseStats`, [`base_stats.py`](app/domain/value_objects/base_stats.py)) : ATK, DEF, PV max. Montées par des **POINTS DE STATS** — 1 par niveau, placés par le joueur via `/stats`. **C'est la seule source de puissance brute du jeu.** 1 point = +2 ATK, ou +2 DEF, ou +50 PV (DEF et PV pèsent le même poids en PV effectifs).
  - **L'équipement, l'arbre et les panoplies s'expriment en POURCENTAGE de ce socle** pour ATK/DEF/PV (clés `attack_pct`, `defense_pct`, `max_hp_pct`). ⚠️ C'est le cœur de la refonte : un objet de fin de jeu offert à un débutant ne multiplie qu'un socle minuscule, il ne peut plus le rendre surpuissant.
  - **Les stats SECONDAIRES restent PLATES** (vitesse, esquive, crit, crit dmg, régén PV, mana max, régén mana) : un « pourcentage de pourcentage de crit » n'a aucun sens lisible. Elles viennent surtout de l'arbre.
  - ⚠️ **Les pourcentages de toutes les sources s'ADDITIONNENT** avant d'être appliqués UNE SEULE FOIS au socle (+20 % équipement et +15 % arbre = +35 %, pas ×1,20×1,15), et le cumul est plafonné (`MAX_PERCENT_BONUS`). Multiplier les sources rend l'équilibrage ingérable dès la quatrième.
  - **Aucun niveau requis sur l'équipement** (équipement v2) : tout est en % du socle, une pièce reste utile toute l'aventure. La colonne `level_requirement` existe encore mais n'est plus lue.
  - **Courbe d'XP QUADRATIQUE** : `kills(niveau) = 8 + 0,547 × niveau` → 9 kills au niveau 1, 62 au niveau 99, **~3 500 pour le cap 100** (6 mois assidu à 1 an régulier). Avant c'était 16 kills constant à vie, donc l'écart entre un ancien et un nouveau ne se refermait JAMAIS. Désormais un nouveau gagne 4 niveaux pendant qu'un ancien en gagne 1 : il rattrape en NIVEAUX, l'ancien garde l'avance en TEMPS investi. Plancher de 8 kills au niveau 1 — les premiers niveaux ne tombent pas tout seuls.
  - **`LEVEL_CAP = 100`** : au cap, l'XP n'est plus accumulée (une barre qui se remplit pour rien est plus frustrante qu'un palier assumé).
  - **Quêtes ADAPTÉES à chaque joueur** (25/10/2026, [`quest_generation_service.py`](app/domain/services/quest_generation_service.py), moteur [`quest_engine.py`](app/application/use_cases/quest_engine.py)) : `daily_quests.json` / `weekly_quests.json` sont des MODÈLES (`objective_type`, `quantity` en unités, `scale` count/xp/gold/damage/tanked/healed, `target` "" / `zone_family` / rôle de défi, `roles`) ; au tirage (`ensure_assigned` : `/quetes` avec le rang Discord, ou un combat avec la famille du monstre), chaque joueur reçoit des quêtes CONCRÈTES figées sur l'assignation (colonnes `name`, `description`, `tier`, `objective_type`, `objective_target`, `objective_quantity`, migration `6e1a9c3d8b42`) : famille la plus avancée accessible à son rang (zones `rank` dans `farm_zones.json`, `families_for_rank`) et assez présente dans sa zone (≥ 50 % des apparitions), quantités = « victoires à son niveau » converties sur le joueur de référence, quêtes de rôle d'après ses classes (`player_roles`). Une QUOTIDIENNE se fait seul en un jour (≤ ~6 victoires, ni `group_kill` ni `hp_healed` — test `test_une_quotidienne_se_fait_seul_en_une_journee`). Progression par objectif (`add_progress_for`) : `on_kill(..., group_size)`, `on_hp_healed`, `on_role_trial` (premier essai d'un rôle dans la journée, depuis `role_trials.run_attempt`)…
  - **Récompenses de quêtes indexées sur le niveau** ([`quest_reward_service.py`](app/domain/services/quest_reward_service.py)) : le montant écrit dans `daily_quests.json` / `weekly_quests.json` est la récompense au **niveau 20**, puis × niveau / 20. ⚠️ Pas « montant de niveau 1 × niveau » : simulé, les quêtes valaient alors 2,5× les combats et le niveau 100 tombait en 63 jours.
  - **Simulateur de saison** : `scripts/simulate_season.py` — jours pour atteindre chaque niveau (contenu actuel vs zones complètes), or par source, prix d'une tenue complète par palier. Référence actuelle : ~260 j à 30 min/jour, ~150 j à 1 h/jour (3 min par combat). Or sur 2 ans ≈ 7,4 M (combats 20 %, quêtes 33 %, raid 13 %, daily 34 %). Une tenue complète coûte 3 à 7 % de l'or gagné en atteignant son niveau : prix des artisans volontairement non touchés.
  - **Équipement v2** : rareté, fusion, passifs, forge sacrée par exemplaire — cf. la section « Système d'équipement (v2) ». L'ancienne amélioration +0 → +10 par définition (`player_item_levels`, `UpgradeItemUseCase`) a été SUPPRIMÉE.
  - **Reset de saison** : `scripts/season_reset.py` (aperçu par défaut, `--confirm "SAISON 1"`, sauvegarde SQLite avant écriture) → `reset_season` ([`reset_season.py`](app/application/use_cases/reset_season.py)) : `ResetPlayerUseCase` pour chaque joueur + vidage des tables de saison + action `reset_rank_roles` en file (le bot remet tout le monde au Rang F). Décision : TOUT repart à zéro, seule l'identité Discord reste.
  - **UN SEUL joueur de référence** pour tout le calibrage : [`reference_player.py`](app/domain/services/reference_player.py) — répartition équilibrée des points + équipement attendu `expected_gear_percent(niveau)` : **rampe de 0 % au niveau 1 à `EXPECTED_GEAR_PERCENT` (50 %) au niveau `GEAR_RAMP_END_LEVEL` (15)**. ⚠️ Avant la rampe (audit oct. 2026), tout était calibré sur +50 % dès le niveau 1 : un compte neuf perdait 100 % de ses combats, même contre un slime (désormais palier 1). `restat_mobs`, `restat_bosses`, `calibrate_rank_trials` et `ItemPowerService` en dépendent TOUS. Changer cette définition recalibre tout de façon cohérente ; chaque script avait avant sa propre idée du joueur type, et elles avaient divergé.
  - ⚠️ **Piège de la saison 1** : un build équilibré a désormais **ATK ≈ DEF** (même coût par point). L'ancienne règle « ATK de l'ennemi = 45 % de l'ATK du joueur » place donc l'ennemi SOUS la défense du joueur → plancher de 1 dégât et impasse jusqu'au tour maximum. L'attaque d'un mob ou d'un boss se calcule sur la **défense et les PV** du joueur, jamais sur son attaque.
  - **FORMULE DE DÉGÂTS UNIQUE** (25/10/2026, [`damage_formula.py`](app/domain/services/damage_formula.py), `resolve_hit(attaque, défense) → (dégâts, contrecoup)`) — la même pour TOUS les combats (joueur → monstre, monstre → joueur, invocations, charme allié → allié — épreuves et défis compris) : `dégâts = max(1, max(ATK − DEF, 25 % ATK))` (la défense absorbe au plus 75 %), `contrecoup = max(0, DEF − 75 % ATK)` renvoyé à l'attaquant. Sous 75 %, c'est EXACTEMENT l'ancien `ATK − DEF` : le calibrage des monstres n'a pas bougé. Le **contrecoup** (idée de l'auteur) n'est pas une action (pas de `turns += 1`), ne déclenche aucun effet (riposte, vol de vie, fureur…), ne provoque jamais de contrecoup en retour, ignore boucliers et défense ; il compte dans `damage_dealt` du défenseur ; pas sur une esquive ; pas de contrecoup contre les invocations (pas de PV). Côté monstre → joueur, `_resolve_mob_hit` le pose dans `target["_recoil"]` et l'appelant l'applique via `_recoil_to_mob` (qui revérifie résurrection / soin du chaman : un contrecoup peut achever un monstre). Épines = contrecoup ×1,1 (`thorns_recoil`). Ne pas réintroduire `max(1, ATK − DEF)` à la main nulle part.
  - **Paquet « rôles »** (25/10/2026, issu du labo d'équilibrage : 3 DPS était la meilleure équipe partout, le trio DPS + Tank + Support jamais 1er) : **aggro** (le monstre vise selon `(PV max + 25 × DEF)³`, `THREAT_EXPONENT`, provocation prioritaire), **aura du Soigneur** (`team_damage_percent` 25 sur la case Soigneur → `CombatPassives.team_damage_pct`, la plus forte aura d'un membre VIVANT, une seule par équipe), **soin sous 50 %** (`HEAL_BELOW_PCT` : sinon le Soigneur attaque — seul, il ne frappait jamais), **Assassin ×1,25 / ×1,5** (au lieu de ×2 / ×3 : un DPS tuait un monstre en 1 action dès le niveau 60), **cases de vitesse à +0,5** (`speed_flat` flottant, tronqué sur la stat finale), **vitesse des monstres = vitesse attendue des joueurs** (`expected_speed`), **escalade comptée en actions du MONSTRE**, **Garde offensive** (`defense_to_attack_percent` → `SkillBonuses.defense_to_attack_percent`, appliqué en DERNIER par `StatsService` : à 100 %, le power score du tank dépassait celui du DPS ; depuis l'étape 3, 25 % sur le Gardien + 25 % sur le Rempart), **élites de groupe** calibrées sur le trio. Mesuré dans le vrai code (`verify` du labo) : trio 1er dans 15 cas sur 21, rang moyen 1,4/10 ; les exceptions (frappe de zone, boss en rafale) favorisent 2 DPS — c'est voulu, chaque monstre demande de s'adapter.
  - **Les classes ne donnent plus de stats** : ce sont des cases de l'arbre (hexagones, effet `grant_class`). L'ARBRE DES CLASSES (pyramide) est reporté après la V1.

- **V2 — stats & progression** (ANCIEN modèle, conservé pour mémoire) :
  - **Combat SOUSTRACTIF** : `dégâts = max(1, ATK_crité − DEF)`, crit AVANT défense (perce l'armure), **sans cap** sur crit_damage. Parité voulue : 1 ATK = 1 DEF. Mob DEF ne doit jamais approcher l'ATK joueur (anti-plancher ; Blindé capé à 70% ATK joueur).
  - **Aucune stat au level-up** : `StatsService` base CONSTANTE (100 PV / 10 ATK / 5 DEF). Le niveau ne donne qu'**1 point de compétence**. Toute la croissance vient de l'**arbre** + gear/classe/titres.
  - **Arbre = moteur de stats** : nœuds **plats** (`atk_flat`/`def_flat`/`hp_max_flat`) = moteur infini non plafonné ; nœuds **%** plafonnés dans `aggregate_bonuses` (atk/def/hp ≤ +200%, gold/xp ≤ +100%, drop ×2). 3 branches (Attaque/Défense/Utilitaire), chaîne stricte, anneaux 5 simples + 1 spécial. Généré par `scripts/generate_skill_tree.py` (extensible en ajoutant des anneaux).
  - **Mobs** : stats relatives au joueur de référence (`scripts/restat_mobs.py`) — DEF mob ≈ 45% ATK joueur, PV ≈ 11× ATK joueur (~20 coups), XP/kill = 6.25·L, or/kill = 3·L. Archétypes standard/brute/blindé/rapide. ⚠️ (Saison 1) le **blindé** : DEF ≤ 60 % ATK joueur, PV ×0,9, ATK ×0,7 → ~47 actions, AVANT l'escalade (action 50) ; l'ancien réglage (~95 actions) le rendait imbattable même à son palier. `tests/content/test_mob_balance.py` : chaque monstre battu par le joueur de référence de son palier, et un compte neuf bat le premier monstre.
  - **Courbe d'XP** : `XP_pour_next = 100·L` (LINÉAIRE) → **kills/niveau ≈ 16 CONSTANT**. Géré par `ProgressionService`. **VOULU** (règle « 2 axes sur 3 montent » : la difficulté des mobs ET l'XP requise par niveau montent, mais le NOMBRE de kills/niveau reste ~constant). ⚠️ Ne PAS « corriger » vers `50·L^1.5` — c'est l'ancienne doc qui était fausse.

- **V2.1 — Système élémentaire & compétences** (juin 2026) :
  - **8 éléments** (`Element` dans `enums.py`) : eau/feu/plante (basiques), glace/vent/terre (intermédiaires, **2ᵉ cycle plus fort VOULU** — affinité plus dure à monter), tenebre/lumiere (avancés). Graphe de forces dans [`element_service.py`](app/domain/services/element_service.py) ; **asymétrie assumée** (ne pas « rééquilibrer »).
  - **Affinités joueur** : table `player_element_affinities` (0-100 par élément). **Tout le monde démarre à 0** (saison 1) ; la montée se fait en **farmant des essences**, au rythme du **talent** caché (cf. talents ci-dessous). Visibles dans `/profil` + commande dédiée **`/affinites`** (affinités + progression d'essences par élément).
  - **Essences élémentaires** (juillet 2026) : ressource DÉDIÉE (table `player_element_essences`, compteurs par élément — **pas dans l'inventaire, pas échangeable**). En tuant un mob d'un élément donné on drop des essences de cet élément ; le nombre par kill dépend de la **zone** : fourchette `essences_min`/`essences_max` dans `farm_zones.json`, **tirée aléatoirement dans [min,max] à chaque kill** (clairière 1-1, cimetière 1-2, zone 3 1-3…). Loader `get_essences_range_for_family` → `(min,max)`, roll dans `apply_rewards`. Les essences montent l'affinité **AUTOMATIQUEMENT** au drop : coût du palier **N→N+1 = N+1 essences** du même élément (0→1 coûte 1, …, 99→100 coûte 100). Logique pure dans `ElementAffinityProgressionService` ; drop + conversion dans `EncounterService.apply_rewards` (survivants uniquement, comme le kill) ; notif dans le récap de combat (`PlayerReward.essence_gains` → `_essence_lines`). Les mobs multi-éléments (via `parse_elements`, forward-compat) donnent des essences de **chaque** élément. Au plafond (100, ou plus avec un don), les essences s'accumulent sans effet.
  - **Talents élémentaires (saison 1, octobre 2026)** — [`element_talent_service.py`](app/domain/services/element_talent_service.py) : à la création et à chaque saison, talent **0-10** par élément (colonnes `talent`, `affinity_cap`, `revealed` de `player_element_affinities`, migration `8d2f4a6c1e33` = nouveau tirage pour tous, affinités ET essences à 0). Gain d'essences × (1 + talent/10), **arrondi stochastique**. **Talent 0 = élément mort** : 0 essence, affinité figée à 0, exclu de l'infusion (`best_for(..., dead_elements)`). Chaque mort ⇒ un élément vivant au hasard reçoit +10..30 de talent et +100 de plafond d'affinité (`apply_essences(..., cap=)`). Les 8 morts ⇒ talent 50 / plafond 300 partout. Le Mage garde ses paliers 25/50/100 (rien de plus au-delà de 100).
  - **La voyante (Ysaline, `/voyante`)** : le talent est CACHÉ (❓) jusqu'à ce qu'elle le lise, élément par élément, propre à chaque joueur. Plus d'objet « papier » à acheter puis consommer : on choisit l'élément, on paie, c'est révélé d'un coup — [`RevealElementTalentUseCase`](app/application/use_cases/reveal_element_talent.py), PNJ [`seer_view.py`](app/bot/views/seer_view.py) (panneau `npc_panel`, portrait `assets/npcs/voyante.png`, bouton aussi dans `/affinites`), cog [`seer_cog.py`](app/bot/cogs/seer_cog.py). Prix croissants `reading_prices` (section `voyante` d'`artisans.json`, 1re = 0 = offerte, ~249 k au total) — **puits d'or**, calé pour tout connaître vers la fin du mid-game ; `price_story` = sa justification du prix croissant. L'admin voit les vrais talents sur la fiche joueur. **`/affinites` est une image** ([`affinities_image.py`](app/bot/rendering/affinities_image.py), DA des PNJ/bannière) : une carte par élément (affinité vers le plafond, essences vers le palier, talent, ⚔️ = fort contre) ; `build_affinity_cards` garantit qu'un talent non révélé ne transmet ni sa valeur ni son plafond. Repli sur l'embed texte si le rendu échoue.
  - **Avantage élémentaire** : `damage_multiplier` = 1 + score/100 × 0,30, **SANS plafond** (affinité 300 ⇒ +90 %, et ça s'additionne à la faiblesse de la cible), plancher 0 = **immunité** (résistance symétrique ; ≥ 100 % ⇒ 0 dégât, géré dans `PartyCombatService`). Mobs ET boss ont un `element` (mono-élément V1, `""`=neutre), éditable via `/admin`.
  - **SAISON 1 — plus de compétences élémentaires équipables.** Les 24 compétences et les 2 emplacements (`skill_slot_1/2`, `/competences`) ont été RETIRÉS : toutes les compétences viennent de l'arbre. L'élément se pose **PAR-DESSUS**, automatiquement : [`ElementalInfusionService`](app/domain/services/elemental_infusion_service.py) choisit à chaque coup celui qui frappe le plus fort CETTE cible. « Coup Tranchant » devient « Coup Tranchant de Feu » contre un monstre faible au feu.
  - ⚠️ **La faiblesse ouvre la porte, la MAÎTRISE décide du gain** (`mastery_factor` : 15 % du bonus à affinité 0, 100 % à affinité 100). Sans ce garde-fou, le score élémentaire sature sur la seule faiblesse de la cible et un joueur n'ayant jamais touché au feu infuserait aussi fort qu'un spécialiste — les essences et les affinités ne serviraient plus à rien.
  - Le MOTEUR d'effets (`SkillEffectService`, `skill_loadouts_by_player` dans `PartyCombatService`) est CONSERVÉ pour les futures compétences actives de l'arbre.
  - **Élément d'attaque du joueur** : choisi coup par coup par l'infusion (`ElementalInfusionService`). `active_element` a été SUPPRIMÉ.
  - **Contribution « soin »** en combat = soins + boucliers donnés aux **alliés** uniquement (jamais sur soi).
  - **Câblage** : l'avantage élémentaire est actif dans les encounters (`elemental_mult_by_player` / `incoming_elemental_mult_by_player`) et le world boss.

- **V2.1 — corrections d'audit (juin 2026)** :
  - **`/gather` RETIRÉ** (métiers à retravailler ; `GatherResourceUseCase` conservé non câblé).
  - **Système de quêtes « legacy » NON CÂBLÉ** (audit août 2026) : `quests.json` (22 entrées) est encore seedé dans `quest_definitions` / `player_quest_states` via `seed_content`, mais **aucun use case ni cog ne le lit**. Les quêtes vivantes sont `daily_quests.json` (`/quetes`) et `weekly_quests.json` (`/quetes_hebdo`), qui ont leurs propres tables et use cases. Conservé comme socle pour une future refonte des quêtes (même statut que `/gather`) — ne pas s'y brancher sans décision explicite. `QuestService` (0 référence) et `ClaimWeeklyQuestUseCase` (remplacé par `ClaimAllWeeklyUseCase`) ont été supprimés.
  - **Pas de combat solo dédié** : `FightMobUseCase` **n'existe pas** — tout le PvE passe par les **encounters de groupe** (jouables seul). L'incrément kills/drops/titres vit dans `EncounterService`.
  - **Chaîne Alembic réparée** (rejeu de zéro OK). **SQLite WAL + busy_timeout** activés (`session.py`).
  - **/daily — SAISON 1** ([`daily_reward_service.py`](app/domain/services/daily_reward_service.py)) : 20 × niveau, +3 % par jour de série plafonné à +90 % (30 j) ; chaque jour manqué DIVISE la série par deux. Paliers de série = TITRES à effets faibles (jamais d'objets) : Habitué (7 j, +1 % or/XP), Taverne Addict (30 j, +3 crit dmg), Pilier (100 j, +2 % or/XP). ⚠️ Remplace `streak × 100` sans plafond, qui pesait 84 % de l'or du jeu (36 500/jour à J365 contre 3 000 en combat) ; désormais ~34 %.
  - Webapp : **CSRF** (vérif origine), cookies `secure` via `ADMIN_COOKIE_SECURE`, Alpine/htmx **auto-hébergés**, caches loaders invalidés à chaque écriture de contenu.

## Workflow Git

Dev se fait sur `main`. Pour pousser en staging beta (déployée sur VPS) :

```bash
git checkout beta
git merge main
git push origin beta
git checkout main
```

## Slash commands disponibles

Noms FRANÇAIS (sans accents) — c'est ce que le joueur tape. Liste tirée du code (décorateurs `command(name=…)`), à tenir à jour avec `tuto.txt`.

| Commande | Cog | Rôle |
|---|---|---|
| `/demarrer`, `/help [commande]`, `/ping` | `onboarding_cog`, `help_cog`, `player_cog` | Guide débutant (crée le profil + rôle Rang F), aide paginée par catégorie (`CATEGORIES` dans `help_cog`), ping |
| `/profil [joueur]`, `/or [joueur]`, `/cd [joueur]`, `/affinites [joueur]` | `player_cog` | Consultatives — `joueur` optionnel (défaut : soi). `/profil` = bannière PNG |
| `/stats` | `stats_cog` | **Saison 1** — feuille de perso, placer les points de stats (+2 ATK / +2 DEF / +50 PV) |
| `/arbre [joueur]` | `skill_cog` | Arbre de compétences (image + Investir / Vue web / Reset 7 j) |
| `/epreuve` | `rank_trial_cog` | Épreuve du rang suivant (seuil de puissance puis gardien) |
| `/daily`, `/quetes`, `/quetes_hebdo` | `player_cog`, `daily_quest_cog`, `weekly_quest_cog` | Récompense quotidienne, 3 quêtes/jour, 3 quêtes/semaine |
| `/titre [joueur]`, `/titre_actif` | `title_cog` | Titres débloqués / titre affiché |
| `/inventaire`, `/equipement`, `/equipement_liste` | `player_cog` | Inventaire (consommables + ressources), équipement en image 2 pages, liste des équipements |
| `/equiper`, `/desequiper <slot\|all>`, `/creer_set`, `/equiper_set`, `/supprimer_set`, `/panoplie` | `player_cog`, `panoplie_cog` | Équipement (placement automatique), panoplies (bonus par rareté), loadouts |
| `/forgeron`, `/artisan` | `artisan_cog` | Artisans : **fusion** de deux copies identiques → rareté suivante |
| `/marchand` | `shop_cog` | Achat uniquement |
| `/voyante` | `seer_cog` | Ysaline lit un talent élémentaire caché (prix croissant, 1re offerte) |
| `/utiliser <consommable>`, `/bestiaire` | `player_cog`, `bestiaire_cog` | Consommable, catalogue des monstres |
| `/defi [role]` | `role_trial_cog` | Défis de rôle du jour (DPS / Tank / Soutien) — remplacent les duels JcJ |
| `/boss moi`, `/boss historique`, `/boss list` | `world_boss_cog` | Raid hebdomadaire (contribution, historique, catalogue) |
| `/payer`, `/echange`, `/brocante annonces\|mes_annonces\|vendre\|acheter\|annuler` | `player_cog`, `trade_cog`, `brocante_cog` | Or, échanges, place de marché (5 %) |
| `/classement <catégorie>`, `/chad` | `leaderboard_cog`, `chad_cog` | Classements, rôle @chad |
| (boucle automatique) | `encounter_cog`, `event_cog`, `world_boss_cog`, `admin_bridge_cog` | Spawn d'encounters, événements, raid 21 h, file `admin_commands` |
| `/admin give\|set\|remove <ressource>` | `admin_cog` | **Admin** — or, XP, points d'arbre, **points de stats**, PV/mana courants, série daily |
| `/admin set_level`, `give_item`, `remove_item`, `heal_full`, `set_rank`, `set_kills`, `force_equip`, `force_unequip`, `reset_player`, `defi_cloture` | `admin_cog` | **Admin** — gestion des joueurs (`target: discord.Member`) |
| `/admin spawn_encounter [mob] [élément]`, `start_encounter`, `end_encounter`, `/event spawn`, `/boss spawn\|stop` | `admin_cog`, `event_cog`, `world_boss_cog` | **Admin** — tests et débogage |
| `/admin shop_add\|shop_set\|shop_remove\|shop_set_stock` | `admin_cog` | **Admin** — boutique |
| (webapp) `/admin/*` | webapp | **Admin** — tout le contenu (objets, mobs, zones, scènes, boutique, artisans, titres, quêtes, événements, boss, joueurs), builder d'arbre, actions rapides via `admin_commands` |

## Système d'administration

- **Admins** : Discord IDs listés dans `.env` via `ADMIN_DISCORD_IDS=id1,id2,...` (parsé en liste par `Settings.admin_ids`).
- **Décorateur** `@admin_only` (dans `app/bot/checks/admin_check.py`) à apposer sur toute commande sensible.
- **Targeting** : les commandes consultatives acceptent `target: discord.Member | None`. Quand `target=None` → auto-create du profil de l'auteur. Quand `target` est spécifié → lookup pur, message d'erreur si profil inexistant. Helper : `PlayerCog._resolve_profile`.
- Le cog `AdminCog` n'a **pas** de restriction de canal (`interaction_check`) — admin peut agir depuis n'importe où.

## Restriction de canal : `BetaChannelOnlyMixin`

Convention : la restriction aux salons autorisés (`settings.command_channel_ids`) se fait par **héritage du mixin partagé** [`BetaChannelOnlyMixin`](app/bot/cogs/_mixins.py) — PAS en recopiant `interaction_check` dans chaque cog (c'était le cas avant, 11 copies).

```python
class MyCog(BetaChannelOnlyMixin, commands.Cog):   # ordre important
```

| Cog | Restreint ? | Stratégie |
|---|---|---|
| `player_cog`, `shop_cog`, `skill_cog`, `title_cog`, `trade_cog`, `brocante_cog`, `panoplie_cog`, `bestiaire_cog`, `chad_cog`, `daily_quest_cog`, `weekly_quest_cog`, `onboarding_cog`, `role_trial_cog` | ✅ mixin | Commandes joueur |
| `leaderboard_cog`, `help_cog` | ❌ | Lecture publique |
| `admin_cog` | ❌ | `@admin_only` sur chaque commande |
| `world_boss_cog`, `event_cog` | ❌ | Groupe dédié (`/boss`, `/event`) + `@admin_only` sur les commandes admin |
| `encounter_cog` | n/a | Boucle de spawn, aucune slash command |

Pour un nouveau cog : commandes joueur → hériter du mixin. Admin → groupe dédié + `@admin_only`. Lecture publique → rien.

## Helpers partagés

- `app/shared/formatters.py` : `format_int(value)` — séparateurs d'espaces FR (1500 → "1 500"). Utilisé partout (embeds + use cases). Centralisé pour éviter la duplication.

## Système d'équipement (v2, saison 1 — octobre 2026)

Refonte complète, règles FIXES décidées avec l'auteur. Tout l'ancien équipement a été supprimé (migration `9b3e5f7a2c41`) ; plus de fabrication.

- **Une pièce par monstre** : `mob_definitions.gear_item_code` = la pièce qu'il PORTE (arme, armure, casque, bouclier ; sinon un accessoire). 23 pièces, 23 passifs.
- **Exemplaires, pas d'objets fongibles** : table `player_gear` (une ligne par copie : `rarity`, `forge_level`, `equipped_slot`, `listed`, `source`) — [`GearRepository`](app/infrastructure/db/repositories/gear_repository.py). `EquipmentRepository` n'est plus qu'une VUE des copies portées (même interface qu'avant) ; un index unique partiel `(player_id, equipped_slot)` interdit deux pièces dans un emplacement. Les pièces ne sont JAMAIS dans `player_inventory_items`.
- **Règles pures** : [`gear_service.py`](app/domain/services/gear_service.py) — 6 raretés (commun → mythique), `PRIMARY_MULTIPLIER` 1/1,5/2/3/4/5,5 sur ATK/DEF/PV %, `SECONDARY_MULTIPLIER` 1/1,25/1,5/2/2,5/3 sur le reste (vitesse tronquée à l'entier), `gear_stats(base, rarité, forge)` = SEULE formule des stats d'une copie (StatsService, rendus, admin). Les stats dans `items.json` sont celles du COMMUN.
- **Drop** : 0 ou 1 pièce par kill et par survivant, un seul tirage (`roll_drop`, `DROP_RATES_PCT` 6 / 2,5 / 0,8 / 0,2 / 0,03 / 0,004 %) dans `EncounterService._roll_gear_drop` ; passif Trouvaille : ×1,10 sur les raretés STRICTEMENT inférieures à celle de sa pièce (épique ⇒ commun→rare, légendaire ⇒ →épique, mythique ⇒ →légendaire), jamais sur le mythique (`lucky_find_rarity`). Les « Chance Drop » de l'arbre (plafond ×2 sur les ressources) et les titres Chasseur légendaire comptent aussi, mais BRIDÉS (`drop_bonus` de `roll_drop`) : plafond `GEAR_DROP_BONUS_CAP` ×1,5, du commun à l'ÉPIQUE seulement — légendaire et mythique ne sont pas touchés par ce bonus. Décision de l'auteur (oct. 2026) ; simulé : ~30 % plus rapide en milieu de partie pour qui investit, mythiques inchangés (non bridé, ×2 partout : 14 % → 25 % des assidus par an). Les world boss ne lâchent pas encore de pièce : chacun en aura une plus tard, avec un mode d'obtention pensé pour qu'on ne la farme pas comme un monstre (un boss par semaine). Un mythique est annoncé dans le salon (`encounter_cog._announce_mythics`). Simulé : 1re épique ≈ J30, tenue légendaire ≈ J180, ~10 % des assidus trouvent un mythique dans l'année.
- **Fusion** ([`FuseGearUseCase`](app/application/use_cases/fuse_gear.py), écran [`fusion_view.py`](app/bot/views/fusion_view.py)) : 2 copies de la même pièce ET de la même rareté + or (`FUSION_GOLD` 200 / 1 000 / 6 000 / 40 000) + matériaux de la FAMILLE du monstre (`family_drops.json`, `FUSION_MATERIALS` 5 / 15 / 40 / 100) → 1 copie de la rareté suivante. Borak (arme, bouclier, tête, corps) / Elna (accessoires), selon `categories` d'`artisans.json`. Le légendaire ne fusionne pas ; le mythique est drop-only. La nouvelle copie garde la forge la plus haute et l'emplacement porté. Atomique (rollback si les matériaux manquent). La remise de maîtrise ne porte que sur l'or.
- **Passifs** ([`gear_passives.py`](app/domain/services/gear_passives.py)) : un par pièce, une pièce par passif, actif dès l'ÉPIQUE (`PASSIVE_MIN_RARITY`), n'évolue pas. Appliqués via `CombatPassives.gear` (`resolve_party_passives` / `with_gear_passives`) dans `PartyCombatService` (tests : [`test_gear_passives_combat.py`](tests/domain/test_gear_passives_combat.py)). Règles : effets sur l'ennemi NON cumulables ; « une fois par combat » une seule fois ; effets croissants plafonnés ; pas de réaction en chaîne (riposte / coup double ne redéclenchent rien) ; économie (Trouvaille, Chasseur d'essences) personnelle, sur les monstres uniquement.
- **Forge sacrée** (événement) : +1 niveau (0 → 10) sur UNE copie choisie, +1 % de ses stats par niveau (`FORGE_BONUS_PER_LEVEL`).
- **Une pièce, une fois** : une même définition ne se porte qu'une fois (armes et accessoires compris) ; demander une meilleure copie d'une pièce portée la remplace dans son emplacement. **Aucun niveau requis.**
- **Échanges / brocante** : une pièce se cède en tant qu'exemplaire (`trade_items.gear_id`, `marketplace_listings.gear_id`, référence UI `gear:<id>` — `gear_ref` / `parse_gear_ref`). En vente, la copie est CONSIGNÉE par `player_gear.listed` : elle reste au vendeur mais `list_owned` l'exclut (ni portée, ni fusionnée, ni échangée) ; transférée à l'achat, libérée à l'annulation / l'expiration. Toutes les raretés s'échangent.
- **Visuels mythiques** ([`mythic_fx.py`](app/bot/rendering/mythic_fx.py)) : cadre animé (GIF, 12 images) sur la carte dans `/equipement_liste` et la grille de `/equipement` — `compose_card_grid_page` / `compose_equipment_grid_page` renvoient alors un `.gif` ; aura sur la bannière `/profil` (`mythic_pieces`).
- **Joueur de référence** : `GEAR_RARITY_CURVE` dans `reference_player.py` (rareté moyenne attendue par niveau) — restat_mobs / restat_bosses / calibrate_rank_trials en dépendent. Sa vitesse inclut les cases de vitesse de l'arbre (`TREE_SPEED` 3 vers le niveau 60, `expected_speed`) ; l'arbre lui donne `expected_tree_pct` (+5 % ATK/DEF/PV dès le niveau 10 par les entrées de voie, ~+9 % au niveau 100 — mesuré sur le généraliste, l'arbre à trois niveaux ne laisse que la moitié des cases).
- **Joueurs de RÔLE** ([`scripts/reference_roles.py`](scripts/reference_roles.py)) : DPS / Tank / Support et un GÉNÉRALISTE (G, points 1/3 partout, classes de base et de jonction) construits avec les vraies règles (points 60/20/20 · 15/42,5/42,5 · 45/20/35, arbre alloué par un glouton aux priorités du rôle dans les règles de l'arbre — seuil de voie, une seule spécialisation — et limité aux classes qui servent le rôle, 7 pièces de la rareté attendue, passifs de rôle, panoplie) — pour calibrer le contenu de GROUPE (élites, boss) et comparer des compositions (`fight("DTS", niveau, mob, capacités)`). Le joueur de référence reste la mesure du contenu SOLO. ⚠️ Un build investi est bien plus fort que le joueur de référence (le DPS a ~2,3× son power score au niveau 100) : il atteint les seuils de rang plus tôt — constaté, pas corrigé (le solo reste accessible, décision de l'auteur).
- **Images** : `assets/items/<code>.png`, prompts dédiés dans `ITEM_IMAGE_PROMPTS` ([`image_gen.py`](webapp/admin/image_gen.py)).
- **Admin** : `/admin give_item` / `remove_item` (rareté + forge pour une pièce) ; webapp : passif sur la fiche objet, exemplaires sur la fiche joueur (donner, équiper, supprimer).

### Emplacements et placement

- **7 emplacements** définis dans `EquipmentSlot` (`app/shared/enums.py`) :
  - `tete` ×1 · `corps` ×1 · `accessoire_1/2/3` (constante `ACCESSORY_SLOTS`) · `arme_1`, `arme_2` (constante `WEAPON_SLOTS`)
  - Armes ET boucliers partagent les deux emplacements d'arme.
- **Deux notions distinctes** : `EquipmentSlot` = l'emplacement PHYSIQUE (stocké dans `player_gear.equipped_slot`) ; `ItemSlotType` = ce qu'un ITEM déclare (`item_definitions.equipment_slot`). Mapping : `SLOTS_FOR_ITEM_TYPE`.
- **Item fields** : `equipment_slot` (type, `None` = non équipable), `requires_two_hands` (occupe `arme_1` ET verrouille `arme_2`), `family` (panoplie), `passive`.
- **Placement automatique** : une seule fonction pure, `plan_equip(item_def, occupied)` ([`equip_item.py`](app/application/use_cases/equip_item.py)) ; le preview de `/equiper` s'en sert pour simuler le diff — ne JAMAIS refaire ce calcul ailleurs. Tests : [`test_equip_planner.py`](tests/domain/test_equip_planner.py).
- **Catégories équipables** : constante `EQUIPABLE_CATEGORIES` (`enums.py`) — source unique.
- **Commandes** : `/equiper <pièce>` (autocomplete `gear:<id>`, copies libres), `/equipement [joueur]` (2 pages image), `/equipement_liste` (une carte par copie : rareté, stats de la copie, passif ✨/🔒, ✅ si portée).

## Système de panoplies (saison 1 — par rareté)

Refonte d'octobre 2026 (idée de l'auteur) : plus de familles d'objets, plus de `sets.json`, plus de `/equiper_panoplie` (`EquipPanoplieUseCase`, `PanoplieCraftsUseCase`, `set_loader` et les pages admin des panoplies ont été supprimés). Le champ `family` des items existe encore mais n'est plus lu.

- **Règle** ([`set_bonus_service.py`](app/domain/services/set_bonus_service.py)) : paliers `TIERS` à 2 / 4 / 7 pièces (×1 / ×1,5 / ×3 du bonus simple), comptés PAR RARETÉ, en **cumulatif** : une pièce compte pour sa rareté et toutes les raretés en dessous ; chaque rareté atteint son palier, les bonus s'additionnent. ⚠️ Avec des groupes stricts, améliorer une pièce pouvait FAIRE BAISSER le bonus (7 rares → 6 rares + 1 épique) ; le cumulatif l'interdit (test `test_ameliorer_une_piece_ne_fait_jamais_baisser_le_bonus`).
- **Marches** `RARITY_STEP` (1 / 0,5 / 0,5 / 1 / 1 / 1,5) : leur somme cumulée = `PRIMARY_MULTIPLIER` de la rareté ⇒ un set d'une seule rareté vaut bonus simple × rareté × palier (7 légendaires en Attaque : 2 % × 4 × 3 = +24 %).
- **Deux mains = 2 pièces** (voulu : une seule pièce à farmer et fusionner pour deux places).
- **Type unique choisi par le joueur** (`PANOPLIE_TYPES` : attaque / défense / PV en %, chance crit, dégâts crit, esquive, régén à plat ; ni vitesse ni économie), stocké dans `players.panoplie_bonus` (migration `4e7a1c9d2b58`), changé librement par `/panoplie` (menu). `resolve_set_bonuses(equipped, profile.player.panoplie_bonus)` dans tous les calculs de stats. Les % sont des FRACTIONS dans `SetBonuses` (comme l'arbre), `total` est en unité d'affichage.
- **Affichage** : `/panoplie` (embed + menu), page 2 de `/equipement` (une ligne par rareté ayant atteint un palier).
- Le joueur de référence n'inclut PAS encore ce bonus.

## Système de trade entre joueurs

- **Modèle DB** : tables `trades` (initiator/target_player_id, status, or offerts, expires_at) et `trade_items` (offered_by initiator/target, item_definition_id, quantity, `gear_id` pour une pièce d'équipement — cf. équipement v2).
- **Statuts** : `pending`, `accepted`, `refused`, `cancelled`, `expired`, `failed` (ressources manquantes à l'accept).
- **Sécurité atomique** : `AcceptTradeUseCase` revérifie les ressources des **deux** joueurs au moment de l'acceptation, pas seulement à la proposition. Si l'un manque de quoi que ce soit → status `failed`, aucun déplacement.
- **TTL** : 5 minutes par défaut. Au-delà, status devient `expired` à la prochaine tentative d'acceptation OU à la prochaine itération du cleanup loop côté bot (`TradeCog.expire_loop`, `tasks.loop(minutes=1)` qui appelle `TradeRepository.expire_overdue_pending` — bulk UPDATE WHERE status=pending AND expires_at < now). Idempotent.
- **Un trade pending par paire** : si Alice→Bob a un trade pending, ni Alice→Bob ni Bob→Alice ne peuvent en proposer un nouveau. Annuler ou attendre l'expiration (le cleanup loop libère automatiquement après 5 min).
- **UI** : `/echange @joueur` → brouillon ephemeral itératif ([`TradeDraftView`](app/bot/views/trade_draft_view.py)) avec 7 boutons. Pas de saisie manuelle de codes : Select Menus listant l'inventaire de l'initiateur ou de la cible (top 25 par quantité), puis modal de quantité. Boutons gold ouvrent une modal mono-champ. Sur Submit → trade créé + message public avec embed + `TradeResponseView` (Accept/Refuse/Cancel) dans [`trade_view.py`](app/bot/views/trade_view.py).

## Système de rang : épreuves

- **Seuils** (25/10/2026) : la puissance du GÉNÉRALISTE au niveau du rang (`reference_roles.gate_power`), gardiens calibrés sur lui (passifs compris) — chacun atteint chaque rang au niveau prévu ou avant (DPS/Tank jusqu'à ~15 niveaux plus tôt ; le soutien grâce à `HEALER_POWER_FACTOR`).
- **Deux verrous, dans cet ordre** : un SEUIL de power score ouvre l'épreuve du rang suivant (« tu as la puissance »), puis il faut BATTRE le gardien en combat solo (« tu sais t'en servir »). Le rang porté est un **rôle Discord** (il ouvre les salons de zone) ; `current_rank(member)` le lit, `set_rank_role` le pose.
- **Contenu** : [`rank_trials.json`](app/infrastructure/content/rank_trials.json) — 8 épreuves (E → SSS). Les gardiens sont **calibrés par simulation** avec le vrai moteur de combat ([`scripts/calibrate_rank_trials.py`](scripts/calibrate_rank_trials.py)) pour ~65 % de victoire chez un joueur qui vient d'atteindre le seuil. Ne pas éditer les stats à la main : relancer le script.
- ⚠️ La **défense du gardien vaut 35 % de l'attaque du joueur de référence** — même invariant que pour les mobs et les boss : au-delà de 75 %, les coups tombent au plancher de 25 % et le contrecoup frappe le joueur. Recalibrés le 25/10/2026 avec la formule unique (65 %) ; les trois rôles passent l'épreuve de leur seuil à 92-100 % (exception mesurée : le tank au seuil du rang B, 38 %).
- **Progression séquentielle** : un joueur rang F très puissant n'obtient pas D d'un coup, il doit passer E d'abord.
- **Échec** ⇒ cooldown (`retry_cooldown_hours`, 6 h par défaut, action_key `rank_trial`). Les PV réels ne sont jamais touchés : l'épreuve est un combat rituel, pas une sortie de farm.

## Système de PNJ : forgeron, artisane, marchand, voyante

On ne tape plus de code d'objet : on parle à quelqu'un.

| Commande | PNJ | Rôle |
|---|---|---|
| `/forgeron` | **Borak** | FUSIONNE `arme`, `bouclier`, `tete`, `corps` |
| `/artisan` | **Elna** | FUSIONNE les `accessoire` |
| `/marchand` | **Sorn** | Vend les articles du shop (achat uniquement) |
| `/voyante` | **Ysaline** | Révèle un talent élémentaire |

- **Équipement v2** : Borak et Elna ne FABRIQUENT plus (fabrication, commandes, attente, boucle `ready_loop`, `ArtisanWorkUseCase`, `ArtisanView` : supprimés). Ils fusionnent — cf. section équipement. Les catégories des deux artisans (`categories` dans [`artisans.json`](app/infrastructure/content/artisans.json)) doivent couvrir `EQUIPABLE_CATEGORIES` sans recouvrement.
- **Maîtrise relationnelle** : `player_artisan_mastery(player_id, artisan_code, orders_completed)`, +1 par fusion. 4 paliers (Apprenti → Légendaire) ; la remise en or s'applique à la fusion. Les tables `player_work_orders` et les recettes (`craft_recipes`) existent encore mais ne servent plus (même statut que `GatherResourceUseCase`, comme `PanoplieCraftsUseCase`).
- **Rendu** : [`npc_panel.py`](app/bot/rendering/npc_panel.py) — portrait + fiche. Portraits sous `assets/npcs/` (générés Cloudflare, DA du jeu).
- **Achat** : `BuyFromShopUseCase`. Toujours pas de vente joueur→shop (décision V2).
- Modification d'`artisans.json` ⇒ **restart du bot** (cache module-level du loader).

## Système d'arbre de compétences

- **Définition** : un seul JSON [`app/infrastructure/content/skill_tree.json`](app/infrastructure/content/skill_tree.json), chargé au boot par [`skill_tree_loader.py`](app/infrastructure/skill_tree/skill_tree_loader.py) (cache module-level). Format **v2** (saison 1) : palettes `shapes` / `node_types` / `link_types` définies par l'auteur, plusieurs `roots`, `links` explicites typés ; le v1 (`root` + `prerequisites`) reste lisible.
- **Règles moteur** (`SkillTreeService`) : **un lien EST un prérequis** (la cible exige la source au niveau MAX ; le `type` du lien n'est que visuel). Une case `start` compte comme **acquise d'office** (le joueur n'y investit jamais). `unlock_rule` par case : `"all"` (défaut — toutes les cases reliées au max, ex. classes aux jonctions) ou `"any"` (une seule suffit). Les **boucles** de liens sont refusées à l'enregistrement (`find_cycle`).
- **Builder visuel** : `/admin/skill-tree/builder` ([`skill_builder_router.py`](webapp/admin/routers/skill_builder_router.py) + [`builder.html`](webapp/templates/admin/skill_tree/builder.html), JS vanilla autonome). Outils Poser / Sélection / Relier / Supprimer (touches 1-4, suppression au clic ou au rectangle), grille polaire aimantée autour de la racine la plus proche (emplacements proposés), undo/redo (Ctrl+Z / Ctrl+Y), Ctrl+S, Ctrl+D, zoom ± , plein écran (F), sélecteur d'icônes (icônes déjà dans le jeu, dédupliquées), gestion des palettes, survol d'un lien dans l'inspecteur ⇒ surbrillance sur le canevas. **Vue joueur** : points illimités, clic = investir, clic droit = retirer, reset en un clic — simulation stockée en `localStorage` uniquement, jamais en base. **Mobile (≤ 900 px)** : barre d'outils en icônes, canevas plein écran et panneaux en feuille du bas (onglets Case/Outils, Détail/Build), pointer events (pincer = zoom, 2 doigts = déplacer, 1 doigt sur le fond = déplacer en Poser/Relier/vue joueur, appui long = retirer en vue joueur), plein écran CSS de repli sur iPhone. Liste de problèmes en direct ; les problèmes bloquants empêchent l'enregistrement (revalidés côté serveur). L'enregistrement passe par `atomic_write_json` (donc git push si `CONTENT_GIT_PUSH`) ⇒ **restart du bot** pour l'appliquer.
- ⚠️ Données injectées dans la page via `_script_json` (PAS le filtre `tojson` de Jinja, qui trie les clés et casserait l'ordre des palettes choisi par l'auteur).
- **Passifs de combat et classes** ([`combat_passives.py`](app/domain/services/combat_passives.py)) : `SkillTreeService.combat_passives(allocations)` agrège les effets des cases investies en un `CombatPassives` (Titan, Résistant, Léthal, Tenace, Vaillant/provocation, AOE, Égide, Rempart, Vampire, Paladin, Soigneur, Buff, Mage) ; les multiplicateurs de critique (Assassin) passent par `SkillBonuses` → `StatsService` (sur la stat finale). Un seul point d'entrée côté application : [`combat_passives_resolver.py`](app/application/services/combat_passives_resolver.py), branché dans **tous** les combats (encounters, world boss, épreuves de rang, défis → `PartyCombatService(passives_by_player=, tactics_by_player=)`), effets de combat des TITRES compris (`with_title_passives`). Règles actées : réductions de dégâts ADDITIONNÉES (alerte du builder au-delà de 25 %, plafond technique 80 %), Mage = GAIN de l'infusion × 1,25 / × 1,5 / × 2 à 25 / 50 / 100 d'affinité, seulement s'il y a infusion (25/10/2026 : avant ×1,5 / ×2 / ×5 sur les DÉGÂTS ENTIERS — mesuré, ×8 contre un monstre faible à 100 d'affinité, une élite tombait en 2 actions ; désormais ×2,2 au lieu de ×1,6, l'ordre de l'Assassin. ⚠️ L'infusion seule à 100 d'affinité, ×1,6, fait déjà gagner 3 DPS contre une élite faible à leur élément : voulu par le design des affinités, à surveiller), Assassin = chances ×1,25 et multiplicateur ×1,5 (25/10/2026, avant ×2 / ×3), soin de base = `BASE_HEAL_PCT` (50 %) de l'attaque, ×2 pour le Soigneur, seulement sur un allié sous `HEAL_BELOW_PCT` (50 %) de ses PV, aura +25 % de dégâts pour l'équipe (une seule), Rempart = Garde offensive (+25 % de sa DEF en ATK, +25 % de plus avec le Gardien). **Escalade** : à partir de la 30e action DU MONSTRE (`boss_turn_count`) puis toutes les 5, il gagne +10 % × palier PAR-DESSUS les paliers précédents (×1,1, puis ×1,1×1,2…) sur attaque, défense, vitesse et critiques — jamais ses PV ni son esquive (ça rallongerait le combat, et les PV du world boss sont conservés). Comptée en actions de tout le monde (avant le 25/10/2026), elle arrivait 3× plus tôt à 3 joueurs et favorisait les DPS ; en solo, c'est le même moment (~50 actions au total). Démarrer au tour 10 faisait tomber le joueur de référence à 27 % de victoires solo. `HARD_MAX_TURNS` (500) reste en dernier recours. AOE stocké mais sans effet tant qu'il n'y a qu'un monstre.
- **Arbre à TROIS NIVEAUX de classes** (étape 3 de la refonte des rôles, 25/10/2026, idée de l'auteur) : cases de combat à 3 points, classes à 2, entrées de voie à 1 — l'arbre de combat coûte ~200 points pour 99 au niveau 100 (avant : 69, tout était acquis vers le niveau 70 et chacun finissait avec les 9 classes ; mesuré : le trio retombait à 3,4/10 et le DPS devenait le meilleur soigneur, les soins se calculant sur l'ATK). **Classes de base** (`base_guerrier` +5 % dégâts, `base_gardien` +50 % d'aggro `threat_percent` / −5 % / Garde 25 %, `base_clerc` 20 % des dégâts soignent l'allié le plus blessé `ally_heal_on_hit_percent`) juste après les entrées, cumulables ; **jonctions** cumulables ; **spécialisations** (Assassin, Rempart, Soigneur) : champs `exclusive_group` (« spécialisation » — une seule par joueur) et `voie_requirement` ({voie: case d'entrée, points: 27} — points investis dans la voie, jonctions comprises) sur la case. Règles dans `SkillTreeService.rule_lock` (branché dans `compute_node_state`, `compute_unlockable_skills`, `validate_investment`, le menu « Investir », l'infobulle web `rule_lock` et la vue joueur du builder). Mesuré (`reference_roles`, vrai code) : spécialisations vers 31 (Rempart 41 chez le tank glouton), solo 100 % pour les 4 profils du niveau 10 à 100, trio rang 2,5/20 compositions (1er 9/21, niveaux 40-100), trio de généralistes 11,8/20 ; Clerc à 20 % = 69 % des soins d'un Soigneur au niveau 100 dans le défi soutien (25 % donnait 90 % : trop proche). Avant le niveau ~31, pas de spécialiste : c'est l'ère généraliste. Migration `8f3b6d1e9a27` : tous les points hors utilité remboursés (y compris d'anciens codes orphelins `atq_*` d'une version antérieure de l'arbre) + rattrapage « au moins niveau − 1 » (sans jamais retirer de points).
- **Tactique** (`/tactique`, colonne `players.combat_tactic`) : égoïste / pragmatique / all-in — cible du sort de soin parmi les alliés sous 50 % de PV, figée pendant le combat ; prévue pour d'autres comportements.
- **Aggro** (`PartyCombatService._single_target`) : hors provocation, un coup mono-cible vise au hasard PONDÉRÉ par `(PV max + 25 × DEF)³` — deux fois plus robuste = huit fois plus visé. Les invocations frappent toujours au hasard.
- **Cases « Confort »** (`unlock_feature`, codes dans `FEATURES`) : `notify_cooldowns` (boucle `NotificationCog`, une fois par échéance via `player_cooldowns.notified_for`, échéances de plus de 30 min ignorées), `notify_events` (MP à chaque `EventCog.spawn_event`), `tower_bonus_ticket` (`TowerTicketsUseCase` : quota journalier UTC 1 + 1, NON cumulable, table `player_tower_tickets` ; la tour solo viendra plus tard et appellera `consume()`).
- **Texte joueur des effets** : [`skill_effect_text.py`](app/domain/services/skill_effect_text.py) (« +1 % d'attaque ») pour le menu Investir et l'infobulle web ; classes du joueur sur la bannière `/profil` (`class_names`).
- **Modèle DB** : table `player_skill_allocations(player_id, skill_code, level)` 1:N. Reset via `player_cooldowns` action_key="skill_tree_reset" : **un par semaine calendaire** (lundi 00h, Europe/Paris), non cumulable (`CooldownService.build_weekly_skill_reset_cooldown`).
- **Convention `values`** : valeurs **cumulatives** au niveau N (lvl 1 → values[0]). Les `costs` restent des deltas (chaque niveau a son coût).
- **Bonus injectés** : `StatsService` accepte un `skill_bonuses: SkillBonuses | None` (4e étage, après équipement/classe, avant les caps). `LootService.generate_loot` accepte un `drop_rate_multiplier`. `EncounterService.apply_rewards` charge les bonus du joueur (xp/gold/drop) avant d'appliquer les récompenses.
- **L'or `/admin give_gold` n'incrémente pas `gold_earned_total`** (career stats), idem les bonus de l'arbre **ne s'appliquent pas** sur l'or admin (pas de double-comptage artificiel).
- **Reset** : `ResetSkillTreeUseCase` (un par semaine calendaire) restitue tous les points dépensés via `compute_total_refund` (les cases de départ ne se remboursent pas). `/admin reset_player` purge aussi les allocations + cooldown.
- **Webapp** : FastAPI mono-service ([`webapp/`](webapp/)), même rendu SVG que le bot. `python -m webapp.main` → http://localhost:8001 (configurable via `WEBAPP_PORT`). Routes :
  - `/skill/<discord_id>` (HTML interactif zoom/pan/hover) + `/api/skill/<discord_id>` (JSON). Le tooltip affiche désormais le **coût du prochain niveau** et la liste des **prérequis** avec leur état (✅ rempli / ❌ manquant). Côté SVG, les arêtes parent → enfant deviennent rouges quand le parent n'est pas encore investi (signal visuel pour guider le joueur vers ce qu'il faut débloquer en premier).
  - **Investir depuis le web** : clic sur une case ⇒ fiche épinglée avec « Investir » (`POST /api/skill/<id>/invest`, même `InvestSkillPointUseCase` que le bot, l'arbre SVG est re-rendu sans recharger). Il faut être connecté : **connexion Discord JOUEUR** ([`webapp/player_auth.py`](webapp/player_auth.py), `/skill/login` / `/skill/logout`) qui RÉUTILISE l'app OAuth et le callback admin (`/admin/auth/callback`) — un cookie `sakura_oauth_next` (ID Discord seul, validé) aiguille le callback vers le parcours joueur. Session joueur = cookie DISTINCT (`sakura_player_session`, autre sel) : jamais de droits admin. On n'investit que dans SON arbre (403 sinon). Le CSRF (vérif d'origine) couvre `/admin` ET `/api/`.
  - `/bestiary` (HTML public, vitrine du jeu) + `/api/bestiary` (JSON). Liste tous les mobs avec stats / drops / power score / rang calculé.
  - `/admin/*` (interface admin protégée par OAuth Discord). Routers dans [`webapp/admin/routers/`](webapp/admin/routers/) — `auth_router` (login/callback/logout), `dashboard_router` (home + 10 stubs), `items_router` et `mobs_router` (CRUD complet **avec** delete). **Mobs reseed-safe** : create/edit écrivent la DB **ET** `mobs.json` (via `content_sync.build_mob_dict`/`upsert_mob_json`, comme les items) — un mob créé/édité au site survit au reseed. Le mob a tous les champs (nom, code, stats, image, élément, famille, drops via éditeur de lignes). **Upload d'image** depuis le site (`webapp/admin/uploads.py`, multipart) : l'image du mob s'uploade et est sauvée dans `assets/mobs/<code>.<ext>` (idem décor de zone → `assets/landscapes/`) ; validée (png/jpg/webp/gif, ≤ 8 Mo), servie via le mount `/assets`, git-pushée avec le contenu (assets trackés → survivent au déploiement). `zones_router` (CRUD des **zones de farm** → `farm_zones.json` zone-centré : nom, channel_id, familles[], décor, fourchette d'essences min/max) et `families_router` (vue d'ensemble read-only : famille → mobs + zone + drop commun). ⚠️ Un changement de zone nécessite un **restart du bot** (process séparé, cache module-level `farm_zone_loader`). Auth : session signée via `itsdangerous` (cookie `sakura_admin_session`, 7j). Vérifie `discord_id ∈ settings.admin_ids`. Templates Jinja2 dans [`webapp/templates/admin/`](webapp/templates/admin/), CSS Sakura pastel rose/violet avec dark mode (toggle Alpine.js stocké en `localStorage`).
  - **Config OAuth** ([`settings.py`](app/infrastructure/config/settings.py)) : `discord_client_id`, `discord_client_secret`, `oauth_redirect_uri`, `admin_session_secret`. À ajouter dans `.env` du VPS + déclarer le redirect URI exact dans Discord Developer Portal (OAuth2 → Redirects). En cas de rotation du secret, redéployer.
  - **Ordre de montage** des routers dans [`webapp/main.py`](webapp/main.py) : `auth` → `items` → `mobs` → `zones` → `familles` → `shop` → `players` → `roles` → `actions` → `content` → `dashboard` (fallback, monté en dernier). Toutes les sous-routes doivent être montées avant le dashboard.
  - **Déploiement** : la webapp tourne dans un service systemd SÉPARÉ (`sakura-webapp.service`, port 8001) ; `deploy_beta.sh` ne redémarre QUE `sakura-bot`. Après un changement webapp (nouveaux routers/templates), faire `sudo systemctl restart sakura-webapp` sur le VPS.
- **Bannière `/profil`** ([`profile_banner.py`](app/bot/rendering/profile_banner.py)) : Pillow génère un PNG 1024×880 contenant TOUT le profil. L'embed Discord ne contient que `set_image(attachment://...)` — pas de fields, pas de duplication.
  - **Header** : avatar circulaire, titre (or), nom, niveau · classe, barre XP avec dégradé bleu→cyan, ligne d'infos auto-wrappée sur 2 lignes (or, points de stats et d'arbre à dépenser, daily streak). Badge de rang **avec PWR à l'intérieur** (la lettre F-/SSS+ + `PWR X.XK` en petit dessous, le tout dans un disque coloré selon la lettre).
  - **Cards** : barre verticale d'accent colorée à gauche de chaque carte, couleur dépendant du type de stat (rouge HP, orange ATK, bleu DEF, cyan vitesse, jaune crit, magenta cdmg, vert régen…). 8 stats de combat (PV, Atk, Def, Vit, Crit chance, Crit dégâts, Esquive, Régen) + 8 stats de carrière (Tués, Combats avec %W, Or amassé, Dégâts inf/encaissés, PV soignés, Esquives totales, V/D).
  - **Emojis de stats : UNE seule table**, `STAT_EMOJIS` dans [`enums.py`](app/shared/enums.py) ; `emoji_mappings.py` la ré-exporte (et en dérive `BONUS_EMOJIS`). Il y a eu deux dicts du MÊME nom avec des valeurs différentes — 🌀 valait « esquive » dans le bot et « régén mana » dans l'admin. Ne jamais recréer une copie locale.
  - **Emojis couleur** via [`emoji_text.py`](app/bot/rendering/emoji_text.py) : helper `draw_text_with_emojis` qui segmente texte+emoji et rend chaque segment avec sa font (DejaVuSans pour le texte, NotoColorEmoji pour les emojis). NotoColorEmoji a une taille native fixe (109 px) qu'on redimensionne. Cache LRU sur les rendus d'emoji. Fallback texte brut si la font emoji est absente.
  - **Dépendance VPS** : `fonts-noto-color-emoji` doit être installé (auto via `scripts/deploy_vps.sh` étape 0 si absent). Sans la font, les emojis tombent en boîtes vides — le fallback ne crash pas mais c'est moche.
  - **Fallback** : si la génération échoue (Pillow plante, font manquante critique), retombe sur `build_player_profile_embed` (ancien embed avec fields). Pas de régression.
  - Fichiers stockés dans `assets/generated_profiles/` (gitignoré).
- **Rendu PNG Discord** : SVG → PNG via cairosvg, pas de Chromium ni Playwright.

## Système de consommables

- **Convention** : `category="consumable"` + `stat_bonuses_json={"effect": str, "value": ...}`. V1 supporte uniquement `effect="heal_percent"` (heal X% du max_hp courant, capé à max_hp).
- **Une seule potion** (`potion_soin`) depuis la saison 1 — les potions I/II/III ont été fusionnées. D'autres consommables viendront (contenu).
- **Use case** : [`UseConsumableUseCase`](app/application/use_cases/use_consumable.py) — décrément atomique de l'inventaire, calcul du `max_hp` via `StatsService` (équipement + classe + skill bonuses), update `player_health_state`.
- **Commande** : `/utiliser <item_code>` avec autocomplete sur les consommables actuellement possédés. Refus si pas en inventaire ou si l'item n'est pas marqué consommable.

## Zones de farm et zones prévues (C → S)

- **Ressources** : uniquement les 8 drops de FAMILLE (matériaux de fusion). Les 34 autres ressources (butin des monstres, diamant du coffre) ne servaient plus à rien depuis la fin de la fabrication : supprimées le 25/10/2026 (contenu + migration `2d9c4b7e5f30`, le coffre donne 1 500 or à la place du diamant).
- **Zones ouvertes** (`farm_zones.json` → `zones`) : F Clairière sinistre (slime, gobelin), E Cimetière abandonné (mort-vivant), D Berceau cataclysmique (démoniaque). Rangs atteints par le joueur de référence : F 1–20, E 21–33, D 34–45, C 46–56, B 57–67, A 68–80, S 81–100.
- **Zones prévues** (`planned_zones`, conçues le 24/10/2026, PAS encore ouvertes) : C Sanctuaire primordial (famille `primordial`, 6 monstres), B Éclipse éternelle (`nocturne`, 7), A Cimes des Wyrms (`draconique`, 7), S Faille du Néant (`abyssal`, 7) — 50 monstres au total. Monstres, pièces (stats du commun), drops de famille (`croc_primordial`, `sang_lunaire`, `ecaille_de_dragon`, `eclat_du_neant`) et capacités sont DÉJÀ en contenu. Les 27 nouvelles pièces n'ont PAS encore de passif (`passive: ""`, en attente de validation de l'auteur) ni d'image ; les monstres n'ont pas d'image.
- ⚠️ **Une famille absente de toute zone ouverte spawnerait dans la zone de BASE** (`get_spawn_channel_for_family`) : `farm_zone_loader.unreleased_families()` est filtré au spawn (`encounter_cog._pick_mob_for_zone`) et dans les deux bestiaires (bot + web). L'admin peut quand même forcer un monstre (`/admin spawn_encounter <mob>`) pour tester.
- **Ouvrir une zone** : lui donner un salon et ses décors (spots), la passer de `planned_zones` à `zones`, puis `restat_mobs --zones-v2 --write` (recalage des familles existantes dans leur plage, `ZONES_V2_LEVELS` : sinon les démons resteraient jusqu'au niveau 97) et reseed.
- **Capacités ajoutées** (`mob_ability_service` + `PartyCombatService`) : `poison` (% des PV max par action de la victime, ignore DEF et bouclier, non cumulable), `armor_break` (DEF de la cible −X % pour le combat, plafonné), `regen` (% des PV max par action du monstre, divisé par Anti-soin), `reflect` et `summon` (mêmes mécaniques que les boss). Les 2 plus faibles de chaque famille n'ont pas de capacité. Les monstres du milieu de famille restent faisables seul, les plus forts demandent un groupe (comme les familles existantes).
- ⚠️ **Saignement et poison tombent UNE fois par ACTION de la victime** (`_tick_dots`), pas à chaque tick de jauge : avant (audit du 24/10/2026), le saignement de l'ogre tombait ~10-20 fois par action et chaque tick comptait comme une action (escalade avancée). Même famille de bug que le soin des boss.
- **Élites de groupe** (25/10/2026, `GROUP_ELITES` dans `mob_ability_service`, `is_group_elite`, `ELITE_LABEL`) : le plus fort de chaque famille (gobelin supérieur, liche maudite, archidémon, aigle tempête, comtesse écarlate, dragon ancien, avatar du néant). Stats = standard de son palier × `ELITE_MULT` (×PV, ×ATK) dans `restat_mobs.py`, MESURÉ par `--calibrate-elites` : parmi les réglages que le trio DPS + Tank + Support de son niveau gagne à ≥ 95 % sans mort en 30 à 90 actions, celui où il devance le plus trois DPS. XP (à chacun) et or ×3 (`ELITE_REWARD_MULT`). Un DPS seul n'en bat aucune ; `test_mob_balance` le vérifie. Le bot prévient en rejoignant (`_danger_note`), le bestiaire l'affiche (résumé de capacité préfixé). ⚠️ À relancer (`--calibrate-elites`, recopier, `--write`) après tout changement du moteur, de l'arbre ou des niveaux — et avec `--zones-v2` à l'ouverture des zones.
- La Succube reste impossible SEUL (son charme, voulu) mais le trio la bat ; l'Ange déchu et l'Archidémon (désormais élite) ne sont plus imbattables (mesuré le 25/10/2026).

## Système de world boss

- **Définitions JSON** : [`app/infrastructure/content/boss_definitions.json`](app/infrastructure/content/boss_definitions.json) — 5 bosses progressifs (intro → endgame) avec stats, modifiers, lore. Loader à cache module-level [`boss_definition_loader.py`](app/infrastructure/world_boss/boss_definition_loader.py) (pattern identique à `skill_tree_loader`).
- **Modèle DB** : tables `world_bosses` (1 seul "active" à la fois — instance courante du boss) et `world_boss_participations` (UNIQUE sur boss_id+player_id, cumule damage_dealt/tanked/hp_healed/fights_count). Les définitions vivent dans le JSON, les **instances** vivent en DB.
- **Spawn manuel** : `/boss spawn <boss_code>` (admin) lit la `BossDefinition` depuis le JSON et crée l'instance avec ses stats raw. Refuse s'il y a déjà un boss actif.
- ⚠️ **Le tirage du boss est BORNÉ par la puissance du serveur** (`pick_random_definition(party_attack=…)`, `MIN_DAMAGE_RATIO`) : un boss dont la défense approche l'attaque des joueurs rendrait le raid de la semaine ingagnable. Le filtre écarte ces boss ; si aucun n'est jouable, on prend le plus tendre plutôt que de ne rien lancer.
- **Auto-spawn** : `WorldBossCog.auto_spawn_loop` (`tasks.loop(hours=1)`) appelle `SpawnRandomWorldBossUseCase`. Conditions de spawn : pas de boss actif + (jamais spawné OU dernière défaite > 7j) + tirage random 5%/heure. Sélection pondérée par `spawn_weight`.
- **Channel dédié** : `settings.boss_channel_id` (fallback `encounter_channel_id` si non défini, pour ne pas casser les .env existants).
- **View** : 3 boutons sur le message du boss (Rejoindre / Quitter / Lancer le combat). Le message est édité après chaque action via `WorldBossCog.refresh_boss_message`.
- **Cooldown 1 combat / jour / joueur** : action_key="world_boss_fight" dans `player_cooldowns`, reset à minuit UTC.
- **Bonus d'équipe** : `WorldBossScalingService` applique +5% par participant additionnel (capé à +50%) sur attack/defense/max_hp du joueur. Speed/crit/dodge ne sont PAS boostés (stats tactiques).
- **Modifiers** ([`BossModifierService`](app/domain/services/boss_modifier_service.py)) — appliqués pendant le combat :
  - `damage_immunity_threshold` (int) : ignore chaque COUP < N (appliqué par coup dans la simulation).
  - `auto_heal_per_turn`, `reflect_pct`, `adds` (invocations) : ⚠️ soin et invocations s'appliquent **une fois par TOUR DU BOSS** (`boss_turn_count`). La boucle de `PartyCombatService` avance par ticks de jauge : avant l'audit d'oct. 2026 ils tombaient à chaque tick (×10-20), le Titan et le Dragon encaissaient 0 dégât net. Test : `test_boss_turn_effects.py`.
  - **Les valeurs sont CALCULÉES**, pas saisies : `MODIFIER_DESIGN` dans [`restat_bosses.py`](scripts/restat_bosses.py) exprime chaque capacité en proportion des joueurs du niveau du boss (soin = part des dégâts du raid par tour, immunité = part d'un coup typique, invocations = part de l'ATK du boss). La mesure rejoue le VRAI assaut (capacités + bonus d'équipe + escalade) ; `tests/content/test_boss_balance.py` exige 4 à 9 assauts pour une équipe de 4 de son niveau. Ne pas éditer ces chiffres à la main : relancer le script.
  - **Calibrage sur l'équipe de RÔLES** (25/10/2026, `CALIBRATION_TEAM = "DTSD"`, via `reference_roles`) : quatre joueurs de référence ne faisaient que 5 à 25 % de ses dégâts, un boss calibré sur eux fondait en un assaut. **ATK du boss = 2 × (DEF + 6 % des PV)** du joueur de référence (`BOSS_ATK_MULT`) : à ×1, trois DPS + un support faisaient mieux que l'équipe de rôles contre certains boss. Le seuil d'immunité reste calé sur le coup d'un joueur de RÉFÉRENCE (il punit le sous-niveau).
  - `enrage_below_pct` + `enrage_attack_multiplier` : si current_hp/max_hp ≤ X%, multiplie l'attack du boss
  - `crit_immunity` (bool) : neutralise la crit_chance du joueur (les crits = dmg normaux)
  - Modifier inconnu = ignoré poliment → extensibilité par contenu pur
- **Persistence HP** : le boss garde `current_hp` entre les combats. `hp_regeneration=0` forcé — un boss ne regen jamais ses PV.
- **Récompenses** ([`CompleteWorldBossUseCase`](app/application/use_cases/world_boss.py)) : base de présence + part du pool d'or selon le score de contribution, amplifiées par le palier de contribution ; bonus top-3 et top par catégorie ; loot exclusif ; titre MVP. ⚠️ Tous les montants de la classe sont des montants de **niveau 1**, multipliés par le niveau du joueur (`scale_reward(..., reference_level=1)`).
- **Catalogue** : `/boss list` affiche tous les bosses définis avec leurs stats et particularités (utile pour debug/preview).
- **À faire quand le user enverra ses vraies données** : remplacer/étendre `boss_definitions.json`, ajuster `spawn_probability` du loop si besoin.

## Système de titres

- **Définitions** : [`titles.json`](app/infrastructure/content/titles.json) — Slayer (10% dmg vs famille, 100 kills), titres de la SEMAINE des défis (Fléau +2 % dégâts, Bastion −2 % dégâts reçus, Ange gardien +2 % soins, Champion de la semaine +1 % stats — exclusifs, `condition_type: weekly_role_trial`), Farmer Fou (exclusif), Bourreau (500 kills total → +5 crit_damage), Intouchable (100 esquives en encounter → +1 dodge), titres de série /daily : Habitué (7 j, +1 % or/XP), Taverne Addict (30 j, +3 crit_damage — n'offre plus de potion), Pilier (100 j, +2 % or/XP), Chasseur Légendaire (1 titre par mob, 50 kills → +5% drop rate sur ce mob).
- **Modèle DB** : `player_titles(player_id, title_code, is_active, unlocked_at)` — 1:N avec unicité applicative (pas en DB) sur `(title_code, *)` pour les titres exclusifs.
- **Tracking dodges** : `player_career_stats.dodges_total` (ajouté par migration `9f6c9ab82525_add_dodges_total_to_player_career_stats`). Incrémenté UNIQUEMENT par `PartyCombatService` quand un joueur esquive (encounters de groupe). 
- **Effets passifs** ([`title_bonus_service.py`](app/domain/services/title_bonus_service.py)) — agrégés dans `TitleBonuses` :
  - `damage_bonus_vs_family` / `damage_reduction_from_family` : multiplicateurs par famille (titres Slayer)
  - `champion_all_stats_pct` : +X% sur PV/atk/def (multiplicatif, ceil), +X flat sur speed/regen, +X additif sur crit/dodge/crit_dmg. **Appliqué en 5e étage** dans `StatsService.calculate_player_stats` (après les caps standards — un Champion peut donc dépasser le cap crit/dodge de 1 pt).
  - `gold_xp_bonus_pct` : +X% sur or/xp gagnés en combat (Farmer Fou). Appliqué dans `EncounterService.apply_rewards` UNIQUEMENT au détenteur — les coéquipiers n'en bénéficient pas.
  - `crit_damage_flat` (Bourreau) / `dodge_flat` (Intouchable) : additifs sur la stat correspondante, appliqués au même 5e étage (s'additionnent au champion_all_stats_pct quand les 2 titres coexistent).
  - `drop_rate_bonus_vs_mob[mob_code]` (Chasseur Légendaire) : multiplicateur drop_rate spécifique à un mob (pas une famille). Appliqué dans `EncounterService.apply_rewards` via `LootService(drop_rate_multiplier=base * chasseur_mult)`. Multiplicatif pour préserver la rareté.
  - `daily_bonus_items: list[(item_code, qty)]` : objets octroyés à chaque `/daily` (mécanique conservée ; plus aucun titre ne l'utilise depuis que Taverne Addict donne +3 dégâts critiques).
- **Helper centralisé** : [`resolve_title_bonuses(session, player_id)`](app/application/services/title_bonus_resolver.py) — charge les codes via `PlayerTitleRepository.list_codes_for_player`, charge les `TitleDefinition` via `title_loader`, agrège via `TitleBonusService`. À appeler partout où on calcule des stats ou des récompenses.
- **Titres exclusifs** ([`exclusive_title_service.py`](app/application/services/exclusive_title_service.py)) :
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

## Défis de rôle (`/defi`) — remplacent les duels JcJ

Étape 2 de la refonte des rôles (décision de l'auteur, 25/10/2026). Les duels JcJ (`/duel`, ladder `player_duel_ranks`, `DuelCombatService`, titre Champion 1v1) ont été SUPPRIMÉS (migration `5c8e2a7f4d19`).

- **Règles pures** : [`role_trial_service.py`](app/domain/services/role_trial_service.py) — trois épreuves contre le MÊME adversaire pour tous (celui d'un joueur de niveau `TRIAL_LEVEL` = 50, score BRUT, choix de l'auteur) :
  - ⚔️ **DPS** — le Mannequin ne joue pas (vitesse 0) : dégâts infligés en `DPS_TICKS` (400 ticks de jauge ≈ 40 s — la vitesse compte, `max_ticks` du moteur) ;
  - 🛡️ **Tank** — le Bourreau frappe (×2 un monstre de palier) et l'escalade finit par le K.O. : dégâts encaissés (`damage_tanked`, bruts). ⚠️ **Pas de sort de soin** (`healer=False`) : sinon le Soigneur, qui se soigne seul, gagnait l'épreuve tank ;
  - 💚 **Soutien** — le Bourreau ne frappe qu'une RECRUE (joueur de référence de niveau 50, `RECRUIT_ID` 0) via `escort_ids` du moteur ; l'épreuve s'arrête à sa mort : PV soignés + boucliers donnés. ⚠️ Avec un Bourreau qui frappait tout le monde, le Soigneur se soignait lui-même et ne marquait rien. Personne n'a la classe Soigneur avant ~15 : 0 point avant.
- **Variante du jour** (`VARIANTS`, 4-5 par rôle : Cuirassé, Insaisissable, Miroir / Rafale, Venin, Critiques, Brise-armure / Saignement, Rafale, Coups lourds, Venin) tirée de la DATE (`variant_of_day`, sha256) : la même pour tous. Les « cibles multiples » attendent un moteur à plusieurs monstres.
- **Essais illimités et DÉTERMINISTES** (`attempt_seed(jour, rôle, joueur)`, `run_trial` rétablit l'état du hasard global) : même build ⇒ même score toute la journée ; réessayer n'a de sens qu'après un changement d'équipement / arbre / points / tactique. Résultat immédiat, sans animation.
- **Semaine** (lundi → dimanche, heure de Paris) : par rôle, somme des `BEST_DAYS` (5) meilleurs jours ; **général** = moyenne des trois rôles, chacun ramené à 100 = le meilleur de la semaine (les échelles brutes diffèrent : ~20 000 de dégâts contre ~5 000 de soins). Égalité ⇒ le plus petit `player_id`.
- **Clôture dimanche 20 h** (`RESULTS_HOUR`) : `role_trials.settle_week` — or du podium `REWARD_GOLD_PER_LEVEL` (100 / 60 / 30 × niveau) pour CHAQUE classement (4), titre de la semaine au 1er (`WEEKLY_TITLES`), idempotent via `role_trial_weeks`. Mesuré : la 1re place ≈ 13 % du revenu hebdo d'un joueur type, 26 % au mieux ; tout le podium ≈ le revenu hebdo d'UN joueur. Après 20 h le dimanche, les défis sont fermés jusqu'à minuit (`is_closed`).
- **Persistance** : `role_trial_scores` (UNIQUE joueur + jour + rôle, meilleur score + essais) et `role_trial_weeks` ([`role_trial_repository.py`](app/infrastructure/db/repositories/role_trial_repository.py)). Purgés par `ResetPlayerUseCase` / le reset de saison.
- **Bot** : [`role_trial_cog.py`](app/bot/cogs/role_trial_cog.py) — `/defi` (programme, scores du jour, semaine) et `/defi role:<dps|tank|soutien>` ; `daily_announce_loop` (minuit Paris, programme du jour) et `settle_loop` (toutes les 10 min, clôture la semaine échue + rattrapage de la précédente si le bot était éteint). Salon : `settings.role_trial_channel_id` (défaut = salon général 1485329709201096796, `ROLE_TRIAL_CHANNEL_ID`). `/admin defi_cloture` clôture tout de suite (tests). Embeds : [`role_trial_embeds.py`](app/bot/embeds/role_trial_embeds.py).
- **Classements** : `/classement defi_dps|defi_tank|defi_soutien|defi_general` (semaine EN COURS). Fiche joueur web : section « 🎯 Défis ».
- **Équilibre** : [`test_role_trial_balance.py`](tests/content/test_role_trial_balance.py) — le spécialiste (builds de `reference_roles`) gagne son épreuve dans chaque variante, aux niveaux 30 / 60 / 100.

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
sqlite3 lita_v2.db ".backup 'lita_v2_backup_$(date +%Y%m%d_%H%M%S).db'"   # PAS cp : base en WAL
git pull origin beta
.venv/bin/alembic upgrade head    # ou stamp si schéma déjà aligné manuellement
.venv/bin/python -m app.infrastructure.db.seeders.seed_content
sudo systemctl restart sakura-bot
sudo journalctl -u sakura-bot -n 100 --no-pager
```
