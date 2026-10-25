"""Chargement de l'arbre de compétences.

Deux formats sont acceptés :

  **v1** (historique) — `{"root": ..., "skills": {code: {..., prerequisites}}}`.
  Les liens y sont implicites : ils se déduisent des `prerequisites`.

  **v2** (builder, saison 1) — ajoute les palettes de FORMES, de TYPES et de
  LIENS définies par l'auteur dans l'éditeur visuel, plusieurs racines, et une
  liste de liens explicites et typés.

Un lien EST un prérequis : la cible ne se débloque que si la source est au
niveau maximum. Le `type` d'un lien n'affecte que son apparence. On accepte
donc les deux écritures et on reconstruit toujours les `prerequisites`, ce qui
permet au moteur de jeu de ne connaître qu'une seule notion.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.entities.skill_node import SkillEffect, SkillNode, SkillPosition
from app.domain.entities.skill_tree_definition import SkillLink, SkillTreeDefinition

_CONTENT_PATH = Path(__file__).resolve().parents[1] / "content" / "skill_tree.json"

_cached_definition: SkillTreeDefinition | None = None

#: Palettes par défaut, utilisées tant que l'auteur n'en a pas défini.
DEFAULT_SHAPES: dict[str, dict] = {
    "cercle_depart":    {"label": "Cercle de départ", "geometry": "circle", "size": 34, "ring": True},
    "cercle_stat":      {"label": "Cercle de stats", "geometry": "circle", "size": 20},
    "cercle_stat_plus": {"label": "Cercle de stats renforcé", "geometry": "circle", "size": 27, "ring": True},
    "carre_passif":     {"label": "Petit carré — passif", "geometry": "square", "size": 20},
    "carre_actif":      {"label": "Carré moyen — actif", "geometry": "square", "size": 28},
    "hexagone_classe":  {"label": "Hexagone — classe", "geometry": "hexagon", "size": 32},
}

DEFAULT_NODE_TYPES: dict[str, dict] = {
    "depart":  {"label": "Départ", "color": "#d6b24a"},
    "stat":    {"label": "Stat", "color": "#4a9eff"},
    "passif":  {"label": "Passif", "color": "#6ccd8a"},
    "actif":   {"label": "Actif", "color": "#e2679a"},
    "classe":  {"label": "Classe", "color": "#b48ae8"},
    "utilite": {"label": "Utilité", "color": "#e8b45a"},
}

DEFAULT_LINK_TYPES: dict[str, dict] = {
    "simple":     {"label": "Lien simple", "style": "solid", "width": 3},
    "majeur":     {"label": "Lien majeur", "style": "solid", "width": 6},
    "optionnel":  {"label": "Lien optionnel", "style": "dashed", "width": 2},
}


def _parse_node(code: str, raw: dict) -> SkillNode:
    effects = [
        SkillEffect(type=e["type"], values=e.get("values", []))
        for e in raw.get("effects", [])
    ]
    pos_raw = raw.get("position") or {}
    return SkillNode(
        code=code,
        name=raw.get("name", code),
        description=raw.get("description", ""),
        icon=raw.get("icon", ""),
        max_level=int(raw.get("max_level", 1)),
        costs=list(raw.get("costs", [])),
        effects=effects,
        prerequisites=list(raw.get("prerequisites", [])),
        position=SkillPosition(
            x=int(pos_raw.get("x", 0)), y=int(pos_raw.get("y", 0)),
        ),
        shape=str(raw.get("shape", "cercle_stat")),
        node_type=str(raw.get("node_type", "stat")),
        start=bool(raw.get("start", False)),
        unlock_rule="any" if raw.get("unlock_rule") == "any" else "all",
        exclusive_group=str(raw.get("exclusive_group", "") or ""),
        voie_requirement=_parse_voie_requirement(raw.get("voie_requirement")),
    )


def _parse_voie_requirement(raw) -> dict | None:
    if not isinstance(raw, dict) or not raw.get("voie"):
        return None
    try:
        points = int(raw.get("points", 0))
    except (TypeError, ValueError):
        return None
    return {"voie": str(raw["voie"]), "points": points} if points > 0 else None


def parse_definition(raw: dict) -> SkillTreeDefinition:
    """Construit la définition depuis un dict déjà chargé (testable sans I/O)."""
    nodes_raw = raw.get("nodes") or raw.get("skills") or {}
    skills = {code: _parse_node(code, data) for code, data in nodes_raw.items()}

    links = [
        SkillLink(
            source=str(link.get("from", link.get("source", ""))),
            target=str(link.get("to", link.get("target", ""))),
            type=str(link.get("type", "simple")),
        )
        for link in raw.get("links", [])
    ]
    # Les liens explicites font autorité sur les prérequis : le builder écrit
    # les deux, mais un arbre dessiné à la main peut n'avoir que les liens.
    for link in links:
        node = skills.get(link.target)
        if node is not None and link.source and link.source not in node.prerequisites:
            node.prerequisites.append(link.source)
    # …et réciproquement, un arbre v1 n'a QUE des prérequis : on en déduit les
    # liens pour que le builder puisse l'ouvrir et le redessiner.
    if not links:
        links = [
            SkillLink(source=parent, target=node.code)
            for node in skills.values()
            for parent in node.prerequisites
        ]

    roots = [str(r) for r in raw.get("roots", []) if r in skills]
    if not roots:
        roots = [code for code, node in skills.items() if node.start]
    legacy_root = str(raw.get("root", ""))
    if not roots and legacy_root in skills:
        roots = [legacy_root]

    return SkillTreeDefinition(
        root=legacy_root or (roots[0] if roots else ""),
        skills=skills,
        roots=roots,
        shapes=raw.get("shapes") or dict(DEFAULT_SHAPES),
        node_types=raw.get("node_types") or dict(DEFAULT_NODE_TYPES),
        link_types=raw.get("link_types") or dict(DEFAULT_LINK_TYPES),
        links=links,
    )


def get_definition() -> SkillTreeDefinition:
    """Charge l'arbre depuis le JSON. Cache module-level (chargé une fois)."""
    global _cached_definition
    if _cached_definition is None:
        try:
            with _CONTENT_PATH.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"skill_tree.json invalide ({_CONTENT_PATH}): {e}") from e
        _cached_definition = parse_definition(raw)
    return _cached_definition


def reset_cache() -> None:
    """Force un rechargement du JSON (utile pour les tests et le hot-reload)."""
    global _cached_definition
    _cached_definition = None


def content_path() -> Path:
    return _CONTENT_PATH
