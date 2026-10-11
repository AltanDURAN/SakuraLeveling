"""Éditeur visuel de l'arbre de compétences.

L'arbre de la saison 1 est DESSINÉ par l'auteur du jeu, pas généré par script :
sa forme porte du sens (trois voies de combat qui se rejoignent en classes, une
voie d'utilité à part). Cette page lui donne un canevas, une palette et un
inspecteur, puis écrit `skill_tree.json` au format v2.

Le serveur ne fait que lire et écrire : toute la manipulation vit dans le
navigateur. La sauvegarde est atomique et part sur Git comme le reste du
contenu.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.infrastructure.skill_tree import skill_tree_loader
from webapp.admin import git_sync, json_writer
from webapp.admin.auth import AdminUser, require_admin
from webapp.admin._shared import get_templates

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/skill-tree", tags=["admin-skill-builder"])

CONTENT_FILE = "skill_tree.json"

#: Catalogue des effets qu'un nœud peut porter, groupé pour l'inspecteur.
#: ⚠️ Saison 1 : le POURCENTAGE est réservé à ATK/DEF/PV — toutes les autres
#: stats se donnent en valeurs BRUTES (un « % de % de crit » n'a pas de sens).
EFFECT_CATALOGUE: list[dict] = [
    {
        "group": "Stats de base (en % du socle)",
        "hint": "À doser : ces pourcentages s'additionnent à ceux de l'équipement.",
        "effects": [
            {"type": "atk_percent", "label": "Attaque", "unit": "%", "scale": 0.01},
            {"type": "def_percent", "label": "Défense", "unit": "%", "scale": 0.01},
            {"type": "hp_max_percent", "label": "PV max", "unit": "%", "scale": 0.01},
        ],
    },
    {
        "group": "Stats secondaires (en brut)",
        "hint": "Seule source de ces stats dans le jeu — sans nœud, personne n'en aura.",
        "effects": [
            {"type": "crit_chance_flat", "label": "Chance de critique", "unit": "pts"},
            {"type": "crit_damage_flat", "label": "Dégâts critiques", "unit": "pts"},
            {"type": "dodge_flat", "label": "Esquive", "unit": "pts"},
            {"type": "speed_flat", "label": "Vitesse", "unit": "pts"},
            {"type": "hp_regeneration_flat", "label": "Régén PV", "unit": "pts"},
            {"type": "mana_max_flat", "label": "Mana max", "unit": "pts"},
            {"type": "mana_regeneration_flat", "label": "Régén mana", "unit": "pts"},
        ],
    },
    {
        "group": "Utilité",
        "hint": "La voie d'utilité : or, drop, XP, confort.",
        "effects": [
            {"type": "gold_drop_percent", "label": "Or gagné", "unit": "%", "scale": 0.01},
            {"type": "xp_drop_percent", "label": "XP gagnée", "unit": "%", "scale": 0.01},
            {"type": "drop_rate_multiplier", "label": "Taux de drop", "unit": "×"},
        ],
    },
    {
        "group": "Compétences et classes",
        "hint": "Branchées au combat dans un second temps — on peut déjà les poser.",
        "effects": [
            {"type": "passive_skill", "label": "Compétence passive", "unit": "code"},
            {"type": "active_skill", "label": "Compétence active", "unit": "code"},
            {"type": "grant_class", "label": "Accorde la classe", "unit": "code"},
            {"type": "unlock_feature", "label": "Débloque une fonctionnalité", "unit": "code"},
        ],
    },
]

#: Types d'effets qui produisent une stat (pour le récapitulatif de couverture).
_STAT_EFFECTS = {
    effect["type"]
    for group in EFFECT_CATALOGUE[:3]
    for effect in group["effects"]
}


def _serialise(definition) -> dict:
    """Définition → dict JSON consommé par le canevas."""
    return {
        "version": 2,
        "roots": definition.all_roots,
        "shapes": definition.shapes,
        "node_types": definition.node_types,
        "link_types": definition.link_types,
        "nodes": {
            node.code: {
                "name": node.name,
                "description": node.description,
                "icon": node.icon,
                "shape": node.shape,
                "node_type": node.node_type,
                "start": node.start,
                "max_level": node.max_level,
                "costs": node.costs,
                "effects": [
                    {"type": e.type, "values": e.values} for e in node.effects
                ],
                "position": {"x": node.position.x, "y": node.position.y},
            }
            for node in definition.skills.values()
        },
        "links": [
            {"from": link.source, "to": link.target, "type": link.type}
            for link in definition.links
        ],
    }


def coverage(payload: dict) -> list[dict]:
    """Ce que l'arbre distribue AU TOTAL, toutes branches montées au maximum.

    Le but est de rendre visibles les TROUS : les stats secondaires n'ont plus
    aucune autre source dans le jeu, donc une stat absente de l'arbre est une
    stat que personne n'aura jamais.
    """
    totals: dict[str, float] = {}
    for node in (payload.get("nodes") or {}).values():
        for effect in node.get("effects") or []:
            kind = effect.get("type")
            if kind not in _STAT_EFFECTS:
                continue
            values = effect.get("values") or []
            if not values:
                continue
            try:
                # `values` est CUMULATIF : la dernière entrée est le total du
                # nœud une fois monté au maximum.
                totals[kind] = totals.get(kind, 0.0) + float(values[-1])
            except (TypeError, ValueError):
                continue

    out: list[dict] = []
    for group in EFFECT_CATALOGUE[:3]:
        for effect in group["effects"]:
            out.append({
                "type": effect["type"],
                "label": effect["label"],
                "unit": effect["unit"],
                "group": group["group"],
                "total": round(totals.get(effect["type"], 0.0), 2),
            })
    return out


@router.get("/builder", response_class=HTMLResponse)
async def builder(request: Request, user: AdminUser = Depends(require_admin)):
    payload = _serialise(skill_tree_loader.get_definition())
    return get_templates().TemplateResponse(
        request, "admin/skill_tree/builder.html",
        context={
            "user": user,
            "tree": payload,
            "catalogue": EFFECT_CATALOGUE,
            "coverage": coverage(payload),
        },
    )


@router.get("/builder/data")
async def builder_data(user: AdminUser = Depends(require_admin)):
    return JSONResponse(_serialise(skill_tree_loader.get_definition()))


@router.post("/builder/save")
async def builder_save(request: Request, user: AdminUser = Depends(require_admin)):
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": "Corps JSON illisible."}, 400)

    nodes = payload.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        return JSONResponse(
            {"ok": False, "error": "L'arbre est vide — rien n'a été enregistré."},
            400,
        )

    problems = validate(payload)
    if problems:
        return JSONResponse({"ok": False, "error": " · ".join(problems)}, 400)

    document = {
        "version": 2,
        "roots": payload.get("roots") or [],
        "shapes": payload.get("shapes") or {},
        "node_types": payload.get("node_types") or {},
        "link_types": payload.get("link_types") or {},
        "nodes": nodes,
        "links": payload.get("links") or [],
        # `root` : conservé pour les lecteurs qui ne connaissent que la v1.
        "root": (payload.get("roots") or [next(iter(nodes))])[0],
    }

    json_writer.atomic_write_json(CONTENT_FILE, document)
    skill_tree_loader.reset_cache()
    try:
        git_sync.push_content([CONTENT_FILE], f"arbre de compétences ({user.username})")
    except Exception:  # noqa: BLE001
        _logger.warning("Push git de l'arbre impossible", exc_info=True)

    return JSONResponse({
        "ok": True,
        "nodes": len(nodes),
        "links": len(document["links"]),
        "coverage": coverage(document),
    })


def validate(payload: dict) -> list[str]:
    """Erreurs qui rendraient l'arbre injouable. Pur, donc testable."""
    problems: list[str] = []
    nodes: dict = payload.get("nodes") or {}
    links = payload.get("links") or []
    roots = payload.get("roots") or []

    if not roots:
        problems.append("aucune racine : personne ne pourrait commencer")

    for code, node in nodes.items():
        max_level = int(node.get("max_level", 1) or 1)
        costs = node.get("costs") or []
        if max_level < 1:
            problems.append(f"« {code} » doit avoir au moins 1 niveau")
        if len(costs) != max_level:
            problems.append(
                f"« {code} » : {len(costs)} coût(s) pour {max_level} niveau(x)"
            )
        for effect in node.get("effects") or []:
            values = effect.get("values") or []
            if values and len(values) != max_level:
                problems.append(
                    f"« {code} » : l'effet {effect.get('type')} a {len(values)} "
                    f"valeur(s) pour {max_level} niveau(x)"
                )

    for link in links:
        source, target = link.get("from"), link.get("to")
        if source not in nodes or target not in nodes:
            problems.append(f"lien orphelin {source} → {target}")

    # Un nœud inatteignable est du contenu mort : ni racine, ni relié à rien.
    linked = {link.get("to") for link in links}
    for code in nodes:
        if code not in roots and code not in linked:
            problems.append(f"« {code} » n'est relié à rien — inatteignable")

    return problems[:12]
