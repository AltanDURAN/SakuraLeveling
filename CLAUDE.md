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

## Workflow Git

Dev se fait sur `main`. Pour pousser en staging beta (déployée sur VPS) :

```bash
git checkout beta
git merge main
git push origin beta
git checkout main
```

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
