# Authoring the skill tree

L'arbre de compétences vit dans un seul fichier :
[`app/infrastructure/content/skill_tree.json`](../app/infrastructure/content/skill_tree.json).
Pour ajouter, modifier ou supprimer une compétence, il suffit d'éditer ce
fichier — pas de migration de DB ni de modification de code.

## Format d'un nœud

```json
"force_brute": {
  "name": "Force Brute",
  "description": "Augmente votre attaque (multiplicatif). +1/3/6/10/15%.",
  "icon": "💪",
  "max_level": 5,
  "costs": [1, 2, 3, 4, 5],
  "effects": [
    { "type": "atk_percent", "values": [1, 3, 6, 10, 15] }
  ],
  "prerequisites": ["combat_root"],
  "position": { "x": -360, "y": 320 }
}
```

| Champ | Description |
|---|---|
| `name` | Nom affiché aux joueurs |
| `description` | Aide affichée au survol et dans le Select Menu Discord |
| `icon` | Emoji (un seul caractère idéalement, deux acceptés pour les capstones) |
| `max_level` | Nombre de paliers d'amélioration |
| `costs` | Coût en skill points pour chaque palier (delta par niveau, taille = max_level) |
| `effects` | Liste de bonus ; `values` = valeur **cumulative** au niveau N (taille = max_level) |
| `prerequisites` | Codes des compétences parentes ; toutes doivent être au moins niveau 1 |
| `position` | Coordonnées (x, y) sur le canvas SVG (en pixels logiques) |

## Sémantique des `values` (important)

`values` représente le bonus **cumulé** qu'aura le joueur à chaque palier, **pas le delta** ajouté
à chaque niveau. Exemple :

```
"effects": [{ "type": "atk_percent", "values": [1, 3, 6, 10, 15] }]
```
- À niveau 1 : +1% atk (pas +1%)
- À niveau 2 : +3% atk (pas +1+2 = 3%)
- À niveau 5 : +15% atk

Cela permet d'écrire des courbes non-linéaires de manière intuitive.

## Types d'effets supportés

| Type | Application | Exemple |
|---|---|---|
| `atk_percent` | × `(1 + valeur/100)` sur attack | `15` → +15% atk |
| `def_percent` | × `(1 + valeur/100)` sur defense | `15` → +15% def |
| `hp_max_percent` | × `(1 + valeur/100)` sur max_hp | `25` → +25% PV max |
| `crit_chance_flat` | additif sur 0..100 (cap 75) | `5` → +5% crit |
| `crit_damage_flat` | additif (100 = neutre) | `25` → +25% dégâts crit |
| `dodge_flat` | additif sur 0..100 (cap 50) | `5` → +5% esquive |
| `speed_flat` | additif sur la vitesse | `4` → +4 vitesse |
| `hp_regeneration_flat` | additif sur la régen PV | `9` → +9 PV/min |
| `xp_drop_percent` | multiplicatif additif sur les gains d'XP | `25` → +25% XP gagné |
| `gold_drop_percent` | multiplicatif additif sur les gains d'or | `25` → +25% or gagné |
| `drop_rate_multiplier` | **multiplicatif** sur le taux de drop | `5` → ×1.05 (préserve la rareté) |

Les types inconnus sont ignorés silencieusement à l'agrégation : on peut donc préparer
une nouvelle famille d'effets dans le JSON avant son support côté code.

## Position des nœuds

L'origine `(0, 0)` est la racine. Les y positifs descendent (convention SVG).
La largeur recommandée par branche : ±400 px de marge horizontale autour de la
racine. Les nœuds capstone (qui combinent plusieurs prérequis) se placent sous
la jonction de leurs parents.

## Règle structurelle

L'arbre commence par **un seul** nœud racine. Toutes les autres compétences ont
au moins un prérequis (formant un graphe dirigé acyclique). Une compétence peut
avoir plusieurs prérequis (cas des capstones). Le loader ne valide pas la
structure — éviter les cycles à la main.

## Workflow d'ajout d'une nouvelle compétence

1. Choisir un `code` unique (snake_case)
2. Définir `name`, `description`, `icon`
3. Choisir `max_level` et la courbe de `costs`
4. Choisir un type d'effet supporté + ses `values` cumulatives
5. Lier au moins un prérequis (`prerequisites`)
6. Placer sur le canvas (`position`) — éviter les chevauchements
7. Tester :
   - `python -m app.bot.main` puis `/skill` Discord
   - `python -m webapp.main` puis ouvrir le navigateur sur `http://localhost:8000/skill/<id>`
8. Pas de migration ni de redémarrage seeders nécessaires : le JSON est lu au
   démarrage du bot et de la webapp (cache module-level).
