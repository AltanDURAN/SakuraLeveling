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

Moteur de combat (découpé le 28/11/2026, comportement inchangé) : `party_combat_service.py` (préparation, boucle, résultat) + `party_combat_rules` / `_foes` / `_party` / `_strike` / `_log` (mixins) ; l'état du combat en cours vit sur l'instance (une par combat).
Autres découpages du même jour (déplacements sans réécriture, anciens chemins d'import conservés) : `encounter_rewards` (mixin d'`EncounterService` : `apply_rewards`), `encounter_video` / `encounter_announce` (mixins d'`EncounterCog`), `admin_group` (le groupe `/admin`, partagé) + `admin_players` / `admin_shop` / `admin_items` (mixins d'`AdminCog` ; ⚠️ AUCUNE commande dans `admin_cog.py` : discord.py réexécute le fichier d'une extension à chaque chargement, une commande s'y réinscrirait dans le groupe partagé), `world_boss_fight` / `world_boss_rewards` (cas d'usage du raid), `views/world_boss_view`, `card_foil` (dorure des cartes), `profile_banner_parts`. ⚠️ Un test qui remplace un nom (`monkeypatch.setattr(module, …)`) doit viser le module où le code qui l'utilise vit désormais.

Ordre de lecture conseillé avant patch : `pyproject.toml` → `alembic.ini` → dernière migration → `app/infrastructure/config/settings.py` → couche concernée → tests existants → tâche.

## Invariants métier (non négociables)

- **`Player` n'a PAS de `current_hp`**. Les HP courants viennent de `PlayerHealthState` (stockage dédié + service de régénération).
- **`Player` n'a PAS de `current_mana`** (miroir strict du HP). Le mana courant vit dans `PlayerManaState` (table `player_mana_states`, `PlayerManaRepository`). `mana_max` / `mana_regeneration` sont des STATS calculées (base 100/5 + arbre + gear/classe) ; seul le mana courant est persisté.
- **`hp_regeneration` est OUT-OF-COMBAT uniquement**. La stat ne s'applique JAMAIS pendant un combat (groupe / world boss / épreuve / défi) — elle est purement passive entre les combats, appliquée par `HealthRegenerationService` selon le temps écoulé. Ne pas réintroduire `+= hp_regeneration` dans les boucles de combat.
- **`mana_regeneration` est OUT-OF-COMBAT uniquement** (même règle que `hp_regeneration`). `ManaRegenerationService` (calqué sur `HealthRegenerationService`) régénère le mana/minute entre les combats. Le mana ne remonte JAMAIS pendant un combat : en combat c'est une réserve qui se vide.
- **Compétences actives et mana** : toute compétence qui INTERVIENT en combat puise dans le mana automatiquement, seulement quand l'effet sert ; réserve vide ⇒ l'effet n'a pas lieu. Coûts `MANA_COSTS` (`combat_passives.py`), calibrés par `python -m scripts.measure_mana` ; défis sans coût, épreuves de rang à réserve pleine. Détail : [fondations](docs/systemes/fondations.md#mana).
- **`Stats` est le value object canonique** pour toute stat de combat : `max_hp`, `attack`, `defense`, `crit_chance`, `crit_damage`, `dodge`, `hp_regeneration`, `speed`, `mana_max`, `mana_regeneration`. ⚠️ Toute reconstruction `Stats(...)` (dans `StatsService` étages 6/7, `title_bonus_service`, `skill_bonuses.apply_to_stats`) doit REPORTER `mana_max`/`mana_regeneration`, sinon les défauts=0 les effacent.
- **Conventions des pourcentages** :
  - `crit_chance`, `dodge` : entiers `0..100` (50 = 50%)
  - `crit_damage` : entier, **100 = neutre, 150 = ×1.5** (PAS un float multiplicateur)
- **Snapshots de combat** : `PartyCombatService.players_state` doit contenir toutes les stats pour permettre recalcul du score équipe en cours de combat.
- **Discord interactions longues** : `interaction.response.defer(ephemeral=True)` puis `interaction.followup.send(...)`. Une seule réponse primaire.
- **Images de mobs** : `mob.image_name` (asset local sous `assets/mobs/`), jamais d'URL. Un réglage (taille, décalage) par monstre, le même dans tous les décors de sa zone ; chaque dessin est rangé en noir et blanc (`prepare_mob_art`) puis teinté par élément (`TONE_TARGET`). Détail : [fondations](docs/systemes/fondations.md#images-de-mobs).
- **Famille de mobs** : champ `family` (snake_case) sur `MobDefinition`. Toujours renseigner pour qu'un mob soit comptabilisé dans les classements de famille (ex : "gobelin" pour tous les gobelins).
- **K.O.** : on ne rejoint pas un encounter à 0 PV (régénération comprise) — sinon un joueur à terre mourait au premier coup et touchait quand même l'XP pleine des morts. ⚠️ Les PV sont RELUS au lancement (`resolve_active_encounter`, régénération comprise) : lus à l'inscription, ils perdaient la potion bue et la régénération de l'attente ; un inscrit tombé ailleurs entre-temps ne combat pas. Un joueur ne s'inscrit qu'à UNE zone à la fois (`EncounterCog.register_participant`). En rejoignant, `EncounterService._danger_note` prévient si le monstre est ≥ 1,2× (« Risqué ») ou ≥ 2× (« Très dangereux ») plus puissant, ou s'il reste < 30 % des PV : une zone couvre une large plage de niveaux et le monstre est tiré sans regarder qui le combattra.
- **Potion** (`UseConsumableUseCase`) : la régénération hors combat écoulée est comptée AVANT le soin (elle était effacée), et la potion est refusée (non consommée) si les PV sont déjà pleins.
- **Élixirs d'Elna** : ils ne comptent qu'en combat de zone et au world boss (`elixirs=True`), JAMAIS dans les épreuves de rang, les défis ni le rang affiché (sinon une course à l'or — décision de l'auteur, 26/10/2026). Un même élixir ne se cumule pas (durée renouvelée), des élixirs différents s'additionnent. Cf. section « Elna, l'alchimiste ».
- **Tracking des kills** : table `player_mob_kills` (player_id, mob_code, kill_count). Incrémentée dans `EncounterService.apply_rewards` pour chaque survivant après victoire (il n'y a pas de combat solo dédié).
- **Répartition des récompenses (combat de groupe)** — V2 équilibrage :
  - **Or** : pool **FIXE** = `mob.gold_reward` (PLUS ×survivants), réparti entre survivants selon le **score de contribution multi-métriques** (dégâts infligés, dégâts tankés, PV soignés actifs — `contribution_scores` : une catégorie ne compte pleinement que si elle pèse au moins 25 % de la plus grosse, sinon 8 PV soignés valaient un tiers de l'or ; même formule au raid). Pool fixe ⇒ l'or/heure d'un groupe ≈ celui d'un solo (on tue plus vite mais chacun touche une part plus petite) → **l'or est le régulateur de l'éco** : les power-levelés co-op montent vite en XP mais manquent d'or → sous-équipés → gatés par la difficulté. Mort en combat ⇒ 0 or. `hp_healed` = soins actifs uniquement (pas la régen passive).
  - **XP** : montant plein **ÉGAL pour tous**, aucune variance de puissance, **morts INCLUS** (le mort gagne l'XP + level-up mais ni or ni loot ni kill). En co-op, l'XP totale créée est ×taille du groupe (récompense sociale assumée, pas de cap de joueurs). `RewardDistributionService.distribute_xp(mob_xp_reward, contributions)`.
  - **Drops** : roll indépendant via `LootService` pour chaque survivant ; **drop commun de famille** (via `family_drops.json` + `family_drop_loader`) avec quantité ∝ puissance du mob.
  - **Kill counter** : tous les survivants reçoivent +1 (pas les morts).
  - Le `PlayerReward.contribution_share` (0..1) expose la part calculée pour affichage et debug.
- **Métriques de combat** trackées par `PartyCombatService` dans `PlayerContribution` : `damage_dealt`, `damage_tanked`, `hp_healed` (heal actif uniquement, pas la régen), `survived`, `final_hp`.
- **Affichage du résultat** : UN message par combat de zone — spawn, puis la VIDÉO GIF du combat ([`fight_animation.py`](app/bot/rendering/fight_animation.py)), puis le récapitulatif `BattleSummaryView` (Récompenses ↔ Détails ↔ Journal) ; une fuite devient une fiche. ⚠️ Mémoire : deux vidéos à la fois au plus, la seconde seulement s'il reste 700 Mo disponibles (`render_queue.video_slot`, mesuré sur le VPS le 28/11/2026 : `scripts/measure_video_load.py`). Détail (vidéo, effets, chiffres, mesures) : [fondations](docs/systemes/fondations.md#affichage-du-resultat).
- **Rang du joueur** : deux notions. Le rang GAGNÉ à l'épreuve (F → SSS) ouvre les zones : c'est le rôle Discord, gardé aussi en base (`players.earned_rank`, écrit par `set_rank_role`, rendu au retour d'un joueur par `access.restore` → `ensure_start_rank_role`) ; le Rang F se reçoit en ACCEPTANT LE RÈGLEMENT (cf. « Parcours d'arrivée ») ; c'est lui que montre `/profil`, la puissance en dessous. Le rang de PUISSANCE est dérivé du `power_score` via `PowerScoreService.compute_rank` (paliers stricts **F- → Ω**) et sert au bestiaire et à l'admin. **V2** : le power score = `offensive × PV_effectifs` où la **défense compte en PV-plats** (`PV + DEF×25`, cohérent avec le combat soustractif — PAS en %) et le crit en espérance corrigée (`crit_chance × (crit_damage−100)`). Seuils (25/10/2026) calés sur la puissance d'un joueur TYPIQUE — médiane des 4 profils de `scripts/reference_roles.py`, `typical_power` — : un sous-rang tous les 5 niveaux, **niveau 100 typique = rang S**, S+/SS/SSS = au-delà (rapports de l'ancienne table), **Ω** au-delà de SSS+ ; régénérés par `python -m scripts.calibrate_power_ranks --write` (avant, calés sur le joueur de référence sans classes : un joueur investi affichait S+ dès le niveau 70). Le kit de SOUTIEN compte : `calculate_from_stats(stats, passives)` × `HEALER_POWER_FACTOR` (1,45) avec le sort de soin — sans lui, un Soigneur plafonnait à 0,67× un DPS et n'atteignait jamais SS/SSS ; puissance d'un JOUEUR = `resolve_player_power` (profil, épreuve, classement, admin). Pas persisté — toujours recalculé. Mapping tiers (admin) : F=Fer, E=Bronze, D=Argent, C=Or, B=Platine, A=Émeraude, S=Diamant, SS=Master, SSS=Grand Master, Ω=Challenger.
- **SAISON 1 — stats & progression** (refonte d'octobre 2026) — l'essentiel, détail dans [fondations](docs/systemes/fondations.md#saison-1) :
  - 3 stats de BASE (ATK, DEF, PV) montées par les points de stats (1 par niveau : +2 / +2 / +50) — seule source de puissance brute.
  - Équipement, arbre, panoplies, élixirs = POURCENTAGES du socle, ADDITIONNÉS puis appliqués UNE fois (`MAX_PERCENT_BONUS`). Stats secondaires plates.
  - XP quadratique (`kills = 8 + 0,547 × niveau`), XP ×2 sous le niveau 10, `LEVEL_CAP = 100`.
  - FORMULE DE DÉGÂTS UNIQUE `resolve_hit` ([`damage_formula.py`](app/domain/services/damage_formula.py)) : `max(1, max(ATK − DEF, 25 % ATK))` + contrecoup `max(0, DEF − 75 % ATK)`. Ne jamais réécrire `max(1, ATK − DEF)` à la main.
  - UN SEUL joueur de référence ([`reference_player.py`](app/domain/services/reference_player.py)) calibre tout ; l'ATK d'un monstre se calcule sur la DEF et les PV du joueur, jamais sur son ATK.
  - Quêtes adaptées à chaque joueur, récompenses indexées sur le niveau, reset de saison TOUT OU RIEN (`/admin lancer_saison`).

- **V2 — stats & progression** : ANCIEN modèle, remplacé par la saison 1 ; gardé pour mémoire dans [fondations](docs/systemes/fondations.md#v2).

- **Éléments** : 8 éléments, graphe ASYMÉTRIQUE voulu ; affinités montées par les ESSENCES au rythme du TALENT caché (Ysaline le révèle) ; l'INFUSION choisit l'élément coup par coup ; la faiblesse ouvre la porte, la MAÎTRISE décide du gain. Plus de compétences élémentaires équipables. Détail : [fondations](docs/systemes/fondations.md#elements).

- **Corrections d'audit de juin 2026** (`/gather` retiré, quêtes « legacy » non câblées, pas de combat solo dédié, `/daily` saison 1…) : [fondations](docs/systemes/fondations.md#audit-juin-2026).

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
| `/reglement` | `rules_cog` | Le règlement, à accepter (bouton) avant d'avoir accès au bot — cf. « Règlement » |
| `/demarrer`, `/help [commande]`, `/ping` | `onboarding_cog`, `help_cog`, `profile_cog` | Guide débutant (crée le profil + rôle Rang F), aide paginée par catégorie (`CATEGORIES` dans `help_cog`), ping |
| `/tuto` | `tutorial_cog` | Tutoriel RP de Hana (salon tutoriel + salons de commandes) : suivre ou passer, actions vérifiées, 3 potions 100 % PV à la fin |
| `/profil [joueur]`, `/or [joueur]`, `/cd [joueur]`, `/affinites [joueur]` | `profile_cog` | Consultatives — `joueur` optionnel (défaut : soi). `/profil` = bannière PNG |
| `/stats` | `stats_cog` | **Saison 1** — feuille de perso en IMAGE ([`stats_sheet.py`](app/bot/rendering/stats_sheet.py), DA de `/affinites`, 20/11/2026 ; embed texte en repli), placer les points de stats (+2 ATK / +2 DEF / +50 PV) |
| `/arbre [joueur]` | `skill_cog` | Arbre de compétences (image + Investir / Vue web / Reset 7 j) |
| `/epreuve` | `rank_trial_cog` | Épreuve du rang suivant (seuil de puissance puis épreuve de SON rôle face au gardien, annonce dans le général) |
| `/daily`, `/quetes`, `/quetes_hebdo` | `economy_cog`, `daily_quest_cog`, `weekly_quest_cog` | Récompense quotidienne, 3 quêtes/jour, 3 quêtes/semaine |
| `/titre [joueur]`, `/titre_actif` | `title_cog` | Titres débloqués / titre affiché |
| `/inventaire`, `/equipement`, `/equipement_liste` | `equipment_cog` | Inventaire (consommables + ressources), équipement en image 2 pages, liste des équipements |
| `/equiper`, `/desequiper <slot\|all>`, `/creer_set`, `/equiper_set`, `/supprimer_set`, `/panoplie` | `equipment_cog`, `panoplie_cog` | Équipement (placement automatique), panoplies (bonus par rareté), loadouts |
| `/forgeron`, `/alchimiste` | `artisan_cog` | Borak : **fusion** de deux copies identiques → rareté suivante (toutes les pièces) · Elna : **potions** (ingrédients + or) |
| `/marchand` | `shop_cog` | Achat uniquement — outils (cor, sceau, parchemin, jeton, sablier) et cosmétiques |
| `/apparence` | `cosmetic_cog` | Cosmétiques portés sur la bannière `/profil` (fond, cadre, couleur du titre) |
| `/voyante` | `seer_cog` | Ysaline lit un talent élémentaire caché (prix croissant, 1re offerte) |
| `/utiliser <consommable>`, `/bestiaire monstres\|boss` | `equipment_cog`, `bestiaire_cog` | Consommable, bestiaires À DÉCOUVRIR des monstres et des world boss (silhouette tant que non vaincu, victoires) — cf. « Bestiaire » |
| `/defi [role]` | `role_trial_cog` | Défis de rôle du jour (DPS / Tank / Soutien) — remplacent les duels JcJ |
| `/tour` | `tower_cog` | Tour solo : 100 étages, record permanent, récompense du jour |
| `/offrande` | `offering_cog` | Offrande commune : jauge d'or du serveur → une divinité bénit tout le monde 24 h |
| `/lune` | `lunar_cog` | Ciel de Paris : phase, pleines lunes / lunes de sang / éclipses à venir (événements des zones) |
| `/boss moi`, `/boss historique` | `world_boss_cog` | Raid hebdomadaire (contribution, historique) — le catalogue est `/bestiaire boss` |
| `/payer`, `/echange`, `/brocante annonces\|mes_annonces\|vendre\|acheter\|annuler` | `economy_cog`, `trade_cog`, `brocante_cog` | Or, échanges, place de marché (5 %) |
| `/classement <catégorie>`, `/chad` | `leaderboard_cog`, `chad_cog` | Classements, rôle @chad |
| `/records` | `records_cog` | Records du serveur : détenteurs de la nuit, ton meilleur, ce qu'il te manque — cf. « Records » |
| `/booster [nombre]`, `/album [joueur]` | `cards_cog` | Cartes à collectionner : boosters de Sorn (salon des cartes, public), album — cf. « Cartes à collectionner » |
| `/evenement` | `seasonal_cog` | Fêtes du moment : calendrier de l'Avent, cadeau de Noël, boutique d'événement — cf. « Fêtes de décembre » |
| (boucle automatique) | `encounter_cog`, `event_cog`, `world_boss_cog`, `admin_bridge_cog` | Spawn d'encounters, événements, raid 21 h, file `admin_commands` |
| (webapp) `/admin/monitoring/*` | webapp + `monitoring_cog` | **Admin** — Surveillance : stats, suivis, alertes (MP aux admins), rapport hebdo |
| `/admin give\|set\|remove <ressource>` | `admin_cog` | **Admin** — or, XP, points d'arbre, **points de stats**, PV/mana courants, série daily |
| `/admin set_level`, `give_item`, `remove_item`, `heal_full`, `set_rank`, `set_kills`, `force_equip`, `force_unequip`, `reset_player`, `defi_cloture` | `admin_cog` | **Admin** — gestion des joueurs (`target: discord.Member`) |
| `/admin lancer_saison [numero] [annonce]` | `admin_cog` | **Admin** — lance officiellement une saison : aperçu, confirmation tapée, sauvegarde, reset de tout (surveillance comprise), Rang F, annonce |
| `/admin porte [etat] [ouverture]` | `admin_cog` | **Admin** — porte d'entrée avant un lancement : ouverte / testeurs seulement / fermée (cf. « Parcours d'arrivée ») |
| `/admin acces` | `admin_cog` | **Admin** — permissions des salons selon le parcours d'arrivée : aperçu, puis bouton « Appliquer » (cf. « Parcours d'arrivée ») |
| `/admin spawn_encounter [mob] [élément]`, `start_encounter`, `end_encounter`, `/event spawn`, `/boss_admin spawn\|stop` | `admin_cog`, `event_cog`, `world_boss_cog` | **Admin** — tests et débogage (groupes masqués aux joueurs : `default_permissions` ; `@admin_only` reste la vraie protection) |
| `/admin shop_add\|shop_set\|shop_remove\|shop_set_stock` | `admin_cog` | **Admin** — boutique |
| (webapp) `/admin/*` | webapp | **Admin** — tout le contenu (objets, mobs, zones, scènes, boutique, artisans, titres, quêtes, événements, boss, cartes, joueurs), builder d'arbre, actions rapides via `admin_commands` |

## Système d'administration

- **Admins** : Discord IDs listés dans `.env` via `ADMIN_DISCORD_IDS=id1,id2,...` (parsé en liste par `Settings.admin_ids`).
- **Décorateur** `@admin_only` (dans `app/bot/checks/admin_check.py`) à apposer sur toute commande sensible.
- **Targeting** : les commandes consultatives acceptent `target: discord.Member | None`. Quand `target=None` → auto-create du profil de l'auteur. Quand `target` est spécifié → lookup pur, message d'erreur si profil inexistant. Helper : `PlayerLookupMixin._resolve_profile` ([`_mixins.py`](app/bot/cogs/_mixins.py)). ⚠️ `player_cog.py` (1 226 lignes) a été DÉCOUPÉ le 26/10/2026 (roadmap N6) en `profile_cog` (consultation), `equipment_cog` (inventaire, équipement, tenues, `/utiliser`) et `economy_cog` (`/payer`, `/daily`) — mêmes commandes.
- Le cog `AdminCog` n'a **pas** de restriction de canal (`interaction_check`) — admin peut agir depuis n'importe où.

## Restriction de canal : `BetaChannelOnlyMixin`

Convention : la restriction aux salons autorisés (`settings.command_channel_ids`) se fait par **héritage du mixin partagé** [`BetaChannelOnlyMixin`](app/bot/cogs/_mixins.py) — PAS en recopiant `interaction_check` dans chaque cog (c'était le cas avant, 11 copies).

```python
class MyCog(BetaChannelOnlyMixin, commands.Cog):   # ordre important
```

| Cog | Restreint ? | Stratégie |
|---|---|---|
| `profile_cog`, `equipment_cog`, `economy_cog`, `shop_cog`, `skill_cog`, `title_cog`, `trade_cog`, `brocante_cog`, `panoplie_cog`, `bestiaire_cog`, `chad_cog`, `daily_quest_cog`, `weekly_quest_cog`, `onboarding_cog`, `role_trial_cog`, `seasonal_cog` | ✅ mixin | Commandes joueur |
| `leaderboard_cog`, `help_cog`, `records_cog` | ❌ | Lecture publique |
| `cards_cog` | sa propre règle | Salons de commandes + salon des cartes (`gambling_channel_id`) ; `/booster` et ses boutons seulement dans le salon des cartes |
| `rules_cog` | ❌ | `/reglement` marche partout (il faut pouvoir lire le règlement avant de jouer) |
| `admin_cog` | ❌ | `@admin_only` sur chaque commande |
| `world_boss_cog`, `event_cog` | ❌ | Groupe dédié (`/boss`, `/event`) + `@admin_only` sur les commandes admin |
| `encounter_cog` | n/a | Boucle de spawn, aucune slash command |

Pour un nouveau cog : commandes joueur → hériter du mixin. Admin → groupe dédié + `@admin_only`. Lecture publique → rien.

## Helpers partagés

- **Écritures atomiques** ([`unit_of_work.py`](app/infrastructure/db/unit_of_work.py), roadmap N8, 26/10/2026) : les dépôts appellent `commit(session)` (jamais `session.commit()` directement) ; dans un bloc `with atomic(session):`, ce n'est qu'un `flush` et tout est validé ENSEMBLE à la sortie, ou annulé sur exception (blocs imbriquables). `@transactional` sur une méthode de cas d'usage (la session est trouvée sur `self.session` ou un dépôt) ; `get_db_session(atomic=True)` pour un bloc. Atomiques : virement, achat chez Sorn, échange, brocante (4 cas), `/daily`, `/utiliser`, fusion, potions d'Elna, récompenses de combat (`apply_rewards`, PV/mana de fin), world boss (combat et récompenses), clôture des défis. Tests : [`test_unit_of_work.py`](tests/infrastructure/test_unit_of_work.py). ⚠️ Dans un dépôt qui a un paramètre `commit`, la fonction est importée sous le nom `commit_session`. ⚠️ **Verrou d'écriture dès l'entrée** (13/11/2026) : un bloc `atomic` commence par `lock_for_write` — `flush`, `BEGIN IMMEDIATE`, `expire_all` (SQLite seulement). Sans ça, la transaction ne démarrait qu'à la première ÉCRITURE : deux clics du même joueur, traités dans deux threads (`asyncio.to_thread`, chacun sa connexion), lisaient le même état puis écrivaient l'un après l'autre — reproduit : fusion faite deux fois avec deux copies (47 courses sur 100), récompense de la tour payée deux fois (36 sur 200). `@locked_write` pose le même verrou sur un dépôt qui LIT puis ÉCRIT une valeur (`add_gold`, `set_gold`, `add_item`, `remove_item`) ; `allocate_stat_point` est une seule écriture conditionnelle. Règles : toute action qui vérifie puis écrit est dans un bloc `atomic` (ou `@transactional`) ; jamais d'`await` dans un bloc atomique (0 aujourd'hui) ; jamais une seconde session qui écrit ouverte À L'INTÉRIEUR d'un bloc atomique (elle attendrait 15 s le verrou de la première, puis « database is locked »). Tests sur base fichier avec de vrais threads : [`test_write_lock.py`](tests/infrastructure/test_write_lock.py).

- `app/shared/formatters.py` : `format_int(value)` — séparateurs d'espaces FR (1500 → "1 500"). Utilisé partout (embeds + use cases). Centralisé pour éviter la duplication.
- **Pièce d'or** (08/11/2026, dessin de l'auteur) : `GOLD_EMOJI` ([`enums.py`](app/shared/enums.py)) = l'emoji de l'APPLICATION `<:piece_or:1568912634672185405>` (Developer Portal › Emojis) : le bot s'en sert partout, MP compris, sans la permission « emojis externes » (doc Discord) — que @everyone n'a pas dans 10 salons (zones, général, records…). Copie du serveur, pour les joueurs : `<:piece_or:1568910264039116831>`. Devant un MONTANT d'or ; 💰 reste l'icône de la bourse et de l'économie. ⚠️ Discord ne l'affiche ni dans un pied de page, ni dans l'auteur d'une fiche, ni dans le TEXTE d'un bouton ou d'une option de menu : `emoji=GOLD_EMOJI` (garde-fou : [`test_gold_emoji.py`](tests/bot/test_gold_emoji.py)). Dans les IMAGES, 💰 et 🪙 sont dessinés avec la pièce (`emoji_text.IMAGE_EMOJIS`, `assets/others/piece_or.png`, 512 px détourée).

## Systèmes du jeu — fiches détaillées (`docs/systemes/`)

⚠️ **Avant de modifier un système, lire sa fiche** (et la tenir à jour dans le même commit). Le détail vit là ; ce fichier ne garde que l'essentiel.

| Système | Fiche | En bref |
|---|---|---|
| Fondations (combat, progression, éléments, affichage) | [fondations](docs/systemes/fondations.md) | Détail des invariants longs ci-dessus |
| Système d'équipement (v2, saison 1 — octobre 2026) | [equipement](docs/systemes/equipement.md) | Pièces par monstre, exemplaires `player_gear`, 6 raretés, drop, fusion chez Borak, passifs dès l'épique, forge sacrée, 7 emplacements, `plan_equip` |
| Système de panoplies (saison 1 — par rareté) | [panoplies](docs/systemes/panoplies.md) | Bonus par rareté, paliers 2/4/7 cumulatifs, type choisi par le joueur (`/panoplie`) |
| Système de trade entre joueurs | [echanges](docs/systemes/echanges.md) | `/echange` : statuts, revérification atomique à l'acceptation, TTL 5 min, un échange par paire |
| Système de rang : épreuves | [epreuves](docs/systemes/epreuves.md) | Seuil de puissance puis épreuve de SON rôle face au gardien ; `rank_trials.json` calibré par script |
| Système de PNJ : forgeron, alchimiste, marchand, voyante | [pnj](docs/systemes/pnj.md) | Borak (fusion), Elna (potions, élixirs), Sorn (outils, cosmétiques), Ysaline (talents) ; maîtrise, portraits |
| Système d'arbre de compétences | [arbre](docs/systemes/arbre.md) | `skill_tree.json` v2, builder visuel, passifs de combat et classes, trois niveaux, aggro, escalade, multi-ennemis, webapp, bannière `/profil` |
| Système de consommables | [consommables](docs/systemes/consommables.md) | `effect` + `value`, `UseConsumableUseCase`, `/utiliser` |
| Zones de farm et zones prévues (C → S) | [zones](docs/systemes/zones.md) | Zones ouvertes F → A, Faille prévue, ouverture (`open_zones`), capacités, élites de groupe, débutants, meutes, formations |
| Système de world boss | [world-boss](docs/systemes/world-boss.md) | Définitions JSON, élément tiré, choix par niveau du serveur, phases / ultime / gardes, vidéo, images, récompenses, modificateurs calculés |
| Système de titres | [titres](docs/systemes/titres.md) | `titles.json`, effets passifs (`TitleBonuses`), titres exclusifs, hooks de déblocage |
| Défis de rôle (`/defi`) — remplacent les duels JcJ | [defis](docs/systemes/defis.md) | `/defi` : DPS / Tank / Soutien déterministes, variante du jour, semaine, clôture dimanche 20 h |
| Tour solo (`/tour`) | [tour](docs/systemes/tour.md) | `/tour` : 100 étages calibrés (`build_tower`), tickets, récompenses, vidéo |
| Offrande commune (`/offrande`) | [offrande](docs/systemes/offrande.md) | Jauge d'or du serveur, formule réglable, divinités et bénédictions |
| Rythme du jeu (Monde › Rythme) | [rythme](docs/systemes/rythme.md) | `pacing.json` : délais, fenêtres, Lancer, heures calmes (désactivées), veille des zones |
| Événements lunaires (`/lune`) | [lune](docs/systemes/lune.md) | Astronomie de Paris, pleine lune / lune de sang / éclipses, effets sur les zones |
| Tutoriel (`/tuto`) | [tutoriel](docs/systemes/tutoriel.md) | `/tuto` avec Hana, étapes vérifiées, salon en lecture seule, accueil des nouveaux |
| Bestiaire à découvrir (`/bestiaire monstres/boss`) | [bestiaire](docs/systemes/bestiaire.md) | `/bestiaire monstres|boss` à découvrir : silhouette, « ? » des zones pas prêtes |
| Records du serveur (salon des records, `/records`) | [records](docs/systemes/records.md) | 19 records, nuit, titres tournants, salon des records |
| Cartes à collectionner (`/booster`, `/album`) | [cartes](docs/systemes/cartes.md) | Boosters, raretés, brillantes, pétales, effets, rendu, admin, cartes cachées |
| Guides épinglés (world boss, tour solo) | [guides-epingles](docs/systemes/guides-epingles.md) | Guides des salons world boss et tour |
| Événements (coffre, petite fille, forge sacrée) | [evenements](docs/systemes/evenements.md) | Coffre, petite fille, forge sacrée ; page du site ; salons |
| Fêtes de décembre — événements saisonniers (`/evenement`) | [fetes](docs/systemes/fetes.md) | Avent, Noël (SECRET de la petite fille), sucres d'orge, boutiques d'événement, Nouvel An |
| Parcours d'arrivée et accès aux salons (`/admin acces`) | [parcours-arrivee](docs/systemes/parcours-arrivee.md) | Règlement → Rang F → tutoriel → Aventurier → rangs ; `/admin acces`, porte d'entrée |
| Règlement (`/reglement`) | [reglement](docs/systemes/reglement.md) | `/reglement`, acceptation par compte, `rules_gate` |
| Surveillance (site admin › 📊 Surveillance) | [surveillance](docs/systemes/surveillance.md) | Journal `game_events`, photos, analyses, pages, 28 alertes, démo |
| Standard des pages du site admin | [site-admin-standard](docs/systemes/site-admin-standard.md) | Menu source unique, fil d'Ariane, `page_head`, composants, pièges Jinja |
| Écrans en image | [ecrans-image](docs/systemes/ecrans-image.md) | `ui_kit`, couleurs par sens, écrans `/stats` `/quetes` `/daily`… ; repli texte |

## Textes côté joueur — règles (revue du 13/11/2026)

- **On tutoie le joueur** dès que le bot parle à UNE personne (réponse privée, refus, description lue seul). Le « vous » ne reste que pour une annonce adressée à tout le salon (« Rassemblez-vous ! », message du Nouvel An).
- **Mots du jeu, pas d'anglais ni de code** : temps de recharge (pas cooldown), butin (pas drop), échange (pas trade), objet (pas item), emplacement (pas slot), tenue (pas loadout), bonus / malus (pas buff / debuff), Attaque / Défense / Vitesse en toutes lettres ; jamais un code d'objet ni un nom de champ (`crit_damage`, « additif », « multiplicatif ») dans un texte montré.
- **Paramètres des commandes en français sans accent** (`@app_commands.rename` : `joueur`, `montant`, `consommable`, `emplacement`, `categorie`, `titre`, `objet`, `prix_unitaire`, `quantite`, `duree`, `annonce`, `commande`) — le nom Python du paramètre ne change pas.
- **Nombres** : tout montant passe par `format_int` ; « N % » avec une espace ; pluriels calculés (« 1 pièce »).
- **Dégâts critiques** : un bonus plat s'écrit « +5 points de dégâts critiques » (100 = neutre).
- **Le secret de Noël** vaut aussi pour la section admin de `tuto.txt` (le fichier est dans le dépôt).

## Parcours joueur — décisions du 14/11/2026

- **Privé** : `/stats`, `/epreuve`, `/cd`, `/or`, `/equiper` (réponse visible du joueur seul) ; `/defi`, `/profil`, `/tour` restent publics. ⚠️ Après un `defer()` public, un `followup.send(ephemeral=True)` est PUBLIC quand même : une commande dont un refus doit rester privé fait `defer(ephemeral=True)`, ou supprime la réponse d'origine avant le refus (`/brocante acheter`).
- **Prochaine étape** ([`next_step.py`](app/application/services/next_step.py)) : une ligne sous la bannière de SON `/profil` — points de stats, points d'arbre, pièce non portée, solde du jour, booster offert, dans cet ordre.
- **Appel à l'aide** d'un monstre : réservé aux inscrits au combat (`EncounterView._is_registered`).
- **Tutoriel** : l'étape `stats` vient APRÈS `tour` (au niveau 1 il n'y a aucun point à placer) ; l'étape `ville` cite le booster offert.
- **Vues qui s'éteignent** ([`views/_base.py`](app/bot/views/_base.py)) : toute vue du jeu hérite d'`ExpiringView` (ou de `GatedView`, qui en hérite) — à l'expiration, ses boutons sont grisés sur le message du DERNIER clic (jeton de 15 min), ou sur `view.message` si l'écran le pose ; une vue jamais touchée et sans message connu ne modifie rien. Avant, 48 vues sur 51 laissaient des boutons morts (« Échec de l'interaction »). Garde-fou : `test_les_vues_du_jeu_s_eteignent_toutes`.
- **Premières fois** ([`milestones.py`](app/application/services/milestones.py), décision de l'auteur, 14/11/2026) : première pièce épique ou mieux, première élite vaincue (`EncounterCog._announce_firsts`), premier boss de la tour à l'étage 10 (`TowerCog._announce_first_boss`) — annoncées dans le salon général sans mention, une fois par saison (retenues dans le journal, kind `milestone`).
- **Raid** : le bouton `world_boss:vote` s'appelle « Horaires » (gris) : il informe ; plus de marque « prêt ».
- **Rythme** (14/11/2026) : l'auteur garde ses réglages du 13/11 (5 min pour rejoindre, Lancer après 150 s, fuite 4 min, 15 % de meutes) en sachant que le niveau 100 tombe à J356 avec Lancer et pas dans l'année sinon : ne pas le « corriger ».
- **Retours de la pré-bêta (20/11/2026, demandes de l'auteur)** : personne n'avait ouvert `/stats` ni tenté `/epreuve` → bouton « Placer mes points » sous le récapitulatif quand un niveau est gagné (`BattleSummaryView.place_points`, ouvre la feuille de stats en privé) et ligne « Prochaine étape » qui rappelle l'épreuve dès que la puissance requise est atteinte (`next_step._trial_ready`, rang lu dans `players.earned_rank`). Bouton **Lancer** grisé tant qu'il ne peut pas lancer (`EncounterView.sync`), réactivé à l'heure par `EncounterCog._unlock_launch_later`. Annonce de minuit des défis COURTE (`build_day_announcement`, ~210 caractères au lieu de ~830) ; le programme complet reste dans `/defi`.
- **La suite après un gain** : une pièce tombée renvoie à `/equiper`, une promotion nomme la zone ouverte avec son salon (`_opened_zones_line`), un niveau gagné par une quête rappelle `/stats` et `/arbre`.

## Limites de Discord — 13/11/2026

Un embed refusé (400 Bad Request), c'est tout le message qui disparaît. Le 11/11/2026, `/titre` a planté en production (« Embed size exceeds maximum size of 6000 ») : avec les 83 titres du jeu, la liste à débloquer dépassait la limite pour presque tous les joueurs (de 2 à 13 titres débloqués).

- **Garde-fous** : [`app/bot/embeds/limits.py`](app/bot/embeds/limits.py) — `clip`, `chunk_lines`, `fit_lines` (des lignes entières, le reste COMPTÉ : « … et 12 de plus », jamais coupé en silence) et `add_lines` (une liste en un ou plusieurs champs). Toute liste qui grossit avec le jeu (joueurs d'un raid, objets d'un échange, titres, participants d'un événement) passe par eux : jamais de `"\n".join(lines)` nu ni de `[:1024]` dans un champ.
- **`/titre`** : un livre à pages ([`title_embeds.py`](app/bot/embeds/title_embeds.py), `TitleBookView` sur le socle `PagedBookView`) — débloqués, puis à débloquer par section (progression, chasse par famille, titres disputés, world boss, cartes, chasseurs légendaires), le plus proche d'abord ; libellés en clair (`TitleProgress`, une lecture des compteurs par commande au lieu d'une par titre) ; plus de code de titre affiché.
- **Corrigés avec** : victoire du raid (le champ des récompenses dépassait 1 024 caractères à 14 participants ; noms des objets au lieu des codes), échange (au plus `MAX_LOTS_PER_SIDE` = 25 lots par côté, affichés en plusieurs champs), menu de fusion (les lots prêts à fusionner d'abord : au-delà de 25 lots, têtes et corps restaient hors menu), forge sacrée et petite fille (plus de coupe silencieuse), liste des inscrits du raid, MP d'alerte (le lien du site en tête).
- **Marges à connaître** : 51 commandes globales sur 100 ; le groupe `/admin` a 23 sous-commandes sur 25 ; page Détails du récapitulatif de combat à 95 % de la limite avec 30 joueurs et une meute de 3.
- **Tests** : [`test_discord_limits.py`](tests/bot/test_discord_limits.py), [`test_title_book.py`](tests/bot/test_title_book.py) — pire cas réaliste d'une fin de saison (pseudos de 32 caractères, 60 joueurs, tous les titres).

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

## Dépendances (`requirements.lock`)

`pyproject.toml` ne donne que des minimums (`>=`) ; les versions EXACTES sont dans [`requirements.lock`](requirements.lock), installé tel quel par `deploy_vps.sh` (un échec arrête le déploiement avant le redémarrage). Avant (jusqu'au 31/10/2026), `pip install -e .` ne mettait jamais à jour un paquet déjà installé : la prod avait dérivé (Python 3.12 + SQLAlchemy 2.0 contre 3.14 + 2.1 en local, 88 failles connues dont 64 dans Pillow). ⚠️ Le VPS tourne sous **Python 3.12** (Ubuntu 24.04), le poste de dev sous 3.14 : le lock se génère SUR LE VPS.

Mettre à jour :
```bash
# 1. en local : pip install -U <paquets>, puis pytest (avec -W error::DeprecationWarning)
# 2. sur le VPS, dans un venv JETABLE (le bot n'est pas touché) :
python3 -m venv /tmp/sakura-venv-test && /tmp/sakura-venv-test/bin/pip install <mêmes versions>
cd ~/SakuraLeveling && /tmp/sakura-venv-test/bin/python -m pytest -q -p no:cacheprovider
/tmp/sakura-venv-test/bin/pip freeze --exclude pip > requirements.lock   # à rapatrier dans le dépôt
# 3. failles connues : pip install pip-audit && pip-audit -r requirements.lock
```

## Sécurité

- Le token Discord est dans `.env` (gitignored). **Ne jamais le committer ni l'exposer.**
- **Backup** `lita_v2.db` avant toute migration ou seed important.
- **Jamais** `alembic stamp` à l'aveugle — toujours inspecter le schéma réel d'abord (`PRAGMA table_info(...)` + `SELECT * FROM alembic_version`).
- **Jamais** de déploiement prod automatique sans tests qui passent.

## Sauvegardes

- **Chaque nuit à 03:00 UTC** (cron du VPS) : `scripts/backup_db.sh` (`sqlite3 .backup` → `~/sakura-backups/`, 14 jours + `lita_v2_latest.db`) puis `scripts/backup_db_offsite.sh` (copie hors serveur, dépôt GitHub privé `sakura-db-backups`).
- **Hors serveur, version du 13/11/2026** : la sauvegarde est vérifiée (`quick_check`), COMPRESSÉE (gzip, ~5 fois plus petite) et découpée au-delà de 90 Mo (GitHub refuse un fichier de plus de 100 Mo) ; 7 jours (`jours/`) et 4 dimanches (`dimanches/`) dans la branche `sauvegardes`, réécrite chaque nuit en UN commit (taille bornée). Avant, la base entière partait chaque nuit dans l'historique de `main` : le dépôt grossissait sans fin et la sauvegarde serait tombée en panne en silence vers 100 Mo (~330 Mo après un an à 50 joueurs). La branche `main` du dépôt de sauvegardes n'est plus touchée (historique conservé).
- **Restaurer** : `git clone --branch sauvegardes --depth 1 …`, puis dans `jours/<la plus récente>` : `cat lita_v2.db.gz* | gunzip > lita_v2.db` et `PRAGMA integrity_check`.
- **Si elle s'arrête** : alerte critique « Sauvegarde en retard » en MP aux admins (cf. Surveillance).

## Redémarrages

`systemctl restart sakura-bot` envoie SIGTERM : `SakuraBot._stop_cleanly` appelle `EncounterCog.prepare_shutdown` (combats à venir annulés avec `RESTART_NOTE`, combats joués affichés avec leur récapitulatif) ; au retour, `_clean_leftovers` retire ce que l'ancien processus a laissé (après un plantage aussi). Les récompenses sont données avant la vidéo : rien n'est perdu.

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
