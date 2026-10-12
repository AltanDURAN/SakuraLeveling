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

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.infrastructure.skill_tree import skill_tree_loader
from webapp.admin import json_writer
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
                "unlock_rule": getattr(node, "unlock_rule", "all"),
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


def _script_json(data) -> str:
    """JSON à injecter dans un <script type="application/json">.

    ⚠️ Pas le filtre `tojson` de Jinja : il TRIE les clés, et l'ordre des
    palettes (formes, types, liens) est voulu par l'auteur — la forme de départ
    doit venir en premier, pas « Carré moyen » par ordre alphabétique.
    `</` est échappé pour qu'une description ne puisse pas fermer la balise.
    """
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


#: Icônes proposées par le sélecteur, en plus de celles déjà utilisées par
#: l'arbre et par le reste du jeu (stats, éléments, objets, titres).
_CURATED_ICONS: dict[str, str] = {
    "Combat": "⚔️ 🗡️ 🏹 🪓 🔨 ⚒️ 🔱 🪃 🛡️ 💥 🩸 👊 🦾 💀 ☠️ 🎯 🧨",
    "Magie": "✨ 🌟 ⭐ 💫 🔮 🪄 📜 📖 🕯️ 🌙 ☀️ 🌑 🌀 💠 🔷 🔶 ♾️ 🧿",
    "Éléments": "🔥 💧 🌊 🌿 🍃 ❄️ 🌪️ ⚡ 🪨 🌋 🌈 🌫️",
    "Soin & défense": "💚 ❤️ 🩹 💊 🧪 🫀 🫧 🍀 🧱 🏰 ⛑️ 🦺",
    "Créatures & classes": "🧙 🧝 🧛 🥷 🧚 🐉 🦅 🐺 🦁 🐍 🦂 🕷️ 👹 👻 🗿",
    "Utilité": "💰 🪙 💎 🎁 🧭 🗺️ ⏳ ⌛ 📦 🎒 🔑 🗝️ 🏆 🎖️ 👑 📈 ⚙️ 🧰 🛠️ 🍖 🍷",
}


def _icon_library() -> list[dict]:
    """Groupes d'icônes pour le sélecteur — d'abord celles DÉJÀ dans le jeu.

    Une icône n'apparaît qu'une fois, dans le premier groupe qui la contient :
    ⚔️ est à la fois une stat, une catégorie d'objet et une arme, et la voir
    trois fois noie le choix. (Le groupe « Déjà dans l'arbre » est calculé
    côté navigateur, il doit suivre les modifications en cours.)
    """
    from app.shared.enums import CATEGORY_ICONS, ELEMENT_EMOJIS, STAT_EMOJIS

    raw: list[tuple[str, list[str]]] = [
        ("Stats du jeu", list(STAT_EMOJIS.values())),
        ("Éléments du jeu", list(ELEMENT_EMOJIS.values())),
        ("Objets du jeu", list(CATEGORY_ICONS.values())),
    ]
    try:
        titles = json.loads(
            (skill_tree_loader.content_path().parent / "titles.json").read_text(encoding="utf-8")
        )
        title_list = titles if isinstance(titles, list) else titles.get("titles", [])
        raw.append(("Titres du jeu", [t.get("icon") for t in title_list if t.get("icon")]))
    except (OSError, ValueError):
        pass
    raw += [(label, icons.split()) for label, icons in _CURATED_ICONS.items()]

    seen: set[str] = set()
    groups: list[dict] = []
    for label, icons in raw:
        kept = []
        for icon in icons:
            # ⚔ et ⚔️ (avec sélecteur de variante) sont la même icône.
            key = icon.replace("\ufe0f", "")
            if icon and key not in seen:
                seen.add(key)
                kept.append(icon)
        if kept:
            groups.append({"label": label, "icons": kept})
    return groups


@router.get("/builder", response_class=HTMLResponse)
async def builder(request: Request, user: AdminUser = Depends(require_admin)):
    payload = _serialise(skill_tree_loader.get_definition())
    return get_templates().TemplateResponse(
        request, "admin/skill_tree/builder.html",
        context={
            "user": user,
            "tree_json": _script_json(payload),
            "catalogue_json": _script_json(EFFECT_CATALOGUE),
            "icons_json": _script_json(_icon_library()),
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

    # atomic_write_json invalide les caches ET pousse sur git.
    json_writer.atomic_write_json(CONTENT_FILE, document)
    skill_tree_loader.reset_cache()

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

    for code, node in nodes.items():
        if node.get("unlock_rule", "all") not in ("all", "any"):
            problems.append(f"« {code} » : règle de déblocage inconnue")

    # Un nœud inatteignable est du contenu mort : ni racine, ni relié à rien.
    linked = {link.get("to") for link in links}
    for code in nodes:
        if code not in roots and code not in linked:
            problems.append(f"« {code} » n'est relié à rien — inatteignable")

    # Un cycle rend toutes ses cases indéblocables (chacune attend l'autre).
    cycle = find_cycle(nodes, links)
    if cycle:
        problems.append("boucle de liens : " + " → ".join(cycle))

    return problems[:12]


def find_cycle(nodes: dict, links: list) -> list[str] | None:
    """Renvoie un cycle de liens s'il en existe un (sinon None)."""
    graph: dict[str, list[str]] = {code: [] for code in nodes}
    for link in links:
        if link.get("from") in graph and link.get("to") in graph:
            graph[link["from"]].append(link["to"])
    state: dict[str, int] = {}  # 1 = en cours, 2 = terminé
    stack: list[str] = []

    def visit(code: str) -> list[str] | None:
        state[code] = 1
        stack.append(code)
        for nxt in graph[code]:
            if state.get(nxt) == 1:
                return stack[stack.index(nxt):] + [nxt]
            if state.get(nxt) is None:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        state[code] = 2
        return None

    for code in graph:
        if state.get(code) is None:
            found = visit(code)
            if found:
                return found
    return None
