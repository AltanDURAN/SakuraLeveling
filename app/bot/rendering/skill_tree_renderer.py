"""Rendu de l'arbre de compétences en SVG (et PNG via cairosvg) — format v2.

Module partagé entre la commande Discord `/arbre` (PNG embarqué) et la page web
`/skill/<id>` (SVG inline). Il reproduit la **vue joueur du builder admin** :
ce que l'auteur voit en concevant l'arbre est ce que le joueur voit en jeu.

  • la FORME et la TAILLE d'une case viennent de la palette `shapes` ;
  • sa COULEUR vient de son type (`node_types`) ;
  • son CADRE dit son état : gris verrouillée, bleu déblocable, vert en cours,
    or au maximum ;
  • un LIEN prend le style de son type (`link_types`) et s'allume quand la
    case de départ est montée au maximum.

Code pur Python + chaînes : pas de dépendance à un framework graphique.
"""

from __future__ import annotations

import math
from html import escape

import cairosvg

from app.application.use_cases.get_skill_tree_state import SkillTreeState
from app.domain.entities.skill_node import SkillNode
from app.domain.entities.skill_tree_definition import SkillTreeDefinition
from app.domain.services.skill_tree_service import SkillTreeService

# ----- Constantes visuelles (miroir du builder admin) -----

BACKGROUND = "#110e1a"
RING_STEP = 95  # pas de la grille polaire du builder
PADDING = 110
HEADER_HEIGHT = 130
FONT = "DejaVu Sans, -apple-system, 'Segoe UI', sans-serif"
EMOJI_FONT = "'Noto Color Emoji', 'Apple Color Emoji', 'Segoe UI Emoji', sans-serif"

#: Couleur du CADRE selon l'état de la case (identique à la vue joueur du builder).
STATE_COLORS = {
    "locked": "#4a4458",
    "unlockable": "#4aa3ff",
    "in_progress": "#4fc383",
    "maxed": "#f0c45c",
}
LOCKED_FILL = "#3a3446"
LINK_DIM = "#352d4a"

COLORS = {
    "header_text": "#ece4f6",
    "subheader_text": "#b9aed0",
    "label": "#d7cee6",
    "label_outline": BACKGROUND,
    "grid": "#2a2340",
}

DEFAULT_SHAPE = {"geometry": "circle", "size": 20}
DEFAULT_TYPE = {"color": "#4a9eff"}
DEFAULT_LINK = {"style": "solid", "width": 3}


# ------------------------------------------------------------- géométrie --
def _poly(sides: int, r: float, rot: float) -> str:
    return " ".join(
        f"{math.cos(rot + i * 2 * math.pi / sides) * r:.1f},"
        f"{math.sin(rot + i * 2 * math.pi / sides) * r:.1f}"
        for i in range(sides)
    )


def _shape(geometry: str, size: float, attrs: str) -> str:
    """Même géométrie que le builder (cercle, carré, hexagone, losange, octogone)."""
    if geometry == "square":
        s = size * 0.9
        return (
            f'<rect x="{-s:.1f}" y="{-s:.1f}" width="{2 * s:.1f}" height="{2 * s:.1f}" '
            f'rx="{s * 0.22:.1f}" {attrs}/>'
        )
    if geometry == "hexagon":
        return f'<polygon points="{_poly(6, size * 1.08, math.pi / 6)}" {attrs}/>'
    if geometry == "diamond":
        return f'<polygon points="{_poly(4, size * 1.2, -math.pi / 2)}" {attrs}/>'
    if geometry == "octagon":
        return f'<polygon points="{_poly(8, size * 1.05, math.pi / 8)}" {attrs}/>'
    return f'<circle r="{size:.1f}" {attrs}/>'


def _shape_of(definition: SkillTreeDefinition, node: SkillNode) -> dict:
    return (definition.shapes or {}).get(node.shape) or DEFAULT_SHAPE


def _size_of(definition: SkillTreeDefinition, node: SkillNode) -> float:
    try:
        return float(_shape_of(definition, node).get("size", 20))
    except (TypeError, ValueError):
        return 20.0


def _type_color(definition: SkillTreeDefinition, node: SkillNode) -> str:
    return ((definition.node_types or {}).get(node.node_type) or DEFAULT_TYPE).get(
        "color", DEFAULT_TYPE["color"],
    )


def _roots(definition: SkillTreeDefinition) -> list[SkillNode]:
    codes = definition.all_roots
    return [definition.get(c) for c in codes if definition.get(c) is not None]


def _nearest_root(roots: list[SkillNode], node: SkillNode) -> SkillNode | None:
    if not roots:
        return None
    return min(
        roots,
        key=lambda r: math.hypot(
            r.position.x - node.position.x, r.position.y - node.position.y,
        ),
    )


# ------------------------------------------------------------- cadrage --
def _bbox(nodes: list[SkillNode], header: int) -> tuple[int, int, int, int]:
    xs = [n.position.x for n in nodes]
    ys = [n.position.y for n in nodes]
    min_x, max_x = min(xs) - PADDING, max(xs) + PADDING
    min_y, max_y = min(ys) - PADDING - header, max(ys) + PADDING + 20
    # Un arbre très étroit (une seule branche) ne doit pas donner une image en
    # ruban : on garde une largeur minimale lisible.
    width = max(max_x - min_x, 640)
    cx = (min_x + max_x) / 2
    return int(cx - width / 2), int(min_y), int(width), int(max_y - min_y)


def main_tree_view_box(definition: SkillTreeDefinition) -> tuple[int, int, int, int]:
    """Cadre sur l'arbre principal (la racine qui porte le plus de cases).

    Sur un téléphone, tout l'arbre tiendrait dans un timbre-poste : la page web
    s'ouvre sur cet arbre-là, le reste est à un glissement de doigt.
    """
    roots = _roots(definition)
    nodes = list(definition.skills.values())
    if not nodes:
        return _compute_view_box(definition, header=False)
    groups: dict[str, list[SkillNode]] = {}
    for node in nodes:
        root = _nearest_root(roots, node)
        groups.setdefault(root.code if root else "", []).append(node)
    main = max(groups.values(), key=len)
    return _bbox(main, 0)


def _compute_view_box(
    definition: SkillTreeDefinition, header: bool = True,
) -> tuple[int, int, int, int]:
    """ViewBox englobant tout l'arbre, avec la place du bandeau en haut."""
    nodes = list(definition.skills.values())
    if not nodes:
        return (-300, -300 - HEADER_HEIGHT, 600, 600 + HEADER_HEIGHT)
    return _bbox(nodes, HEADER_HEIGHT if header else 0)


# --------------------------------------------------------------- dessin --
def _render_header(
    state: SkillTreeState, vx: int, vy: int, vw: int, ui: float = 1.0,
) -> str:
    title = escape(f"Arbre de {state.player_display_name}")
    sub = escape(
        f"Points disponibles : {state.available_points}   ·   "
        f"Dépensés : {state.spent_points}"
    )
    cx = vx + vw / 2
    return (
        f'<text x="{cx:.0f}" y="{vy + 30 + 16 * ui:.0f}" text-anchor="middle" '
        f'font-family="{FONT}" font-size="{30 * ui:.0f}" font-weight="700" '
        f'fill="{COLORS["header_text"]}">{title}</text>'
        f'<text x="{cx:.0f}" y="{vy + 52 + 26 * ui:.0f}" text-anchor="middle" '
        f'font-family="{FONT}" font-size="{17 * ui:.0f}" '
        f'fill="{COLORS["subheader_text"]}">{sub}</text>'
    )


def _render_background(
    definition: SkillTreeDefinition, states: dict[str, str],
) -> tuple[str, str]:
    """Nébuleuse qui épouse la forme de l'arbre + anneaux de la grille.

    Renvoie (defs, contenu). Les halos sont des dégradés radiaux (cairosvg ne
    sait pas flouter) : même rendu dans Discord et sur le web.
    """
    defs: list[str] = []
    seen: set[str] = set()
    body: list[str] = []

    roots = _roots(definition)
    for root in roots:
        reach = 2
        for node in definition.skills.values():
            if _nearest_root(roots, node) is not root:
                continue
            dist = math.hypot(
                node.position.x - root.position.x, node.position.y - root.position.y,
            )
            reach = max(reach, math.ceil(dist / RING_STEP) + 1)
        for i in range(1, reach + 1):
            body.append(
                f'<circle cx="{root.position.x}" cy="{root.position.y}" r="{i * RING_STEP}" '
                f'fill="none" stroke="{COLORS["grid"]}" stroke-width="1"/>'
            )

    halos: list[str] = []
    for node in definition.skills.values():
        color = STATE_COLORS.get(states.get(node.code, "locked"), STATE_COLORS["locked"])
        gid = "neb-" + color.lstrip("#")
        if gid not in seen:
            seen.add(gid)
            defs.append(
                f'<radialGradient id="{gid}"><stop offset="0%" stop-color="{color}" '
                f'stop-opacity="0.30"/><stop offset="100%" stop-color="{color}" '
                f'stop-opacity="0"/></radialGradient>'
            )
        radius = 160 if node.start else 105
        halos.append(
            f'<circle cx="{node.position.x}" cy="{node.position.y}" r="{radius}" '
            f'fill="url(#{gid})"/>'
        )
    return "".join(defs), "".join(halos) + "".join(body)


def _render_edges(definition: SkillTreeDefinition, states: dict[str, str]) -> str:
    out: list[str] = []
    for link in definition.links:
        src, dst = definition.get(link.source), definition.get(link.target)
        if src is None or dst is None:
            continue
        lt = (definition.link_types or {}).get(link.type) or DEFAULT_LINK
        try:
            width = float(lt.get("width", 3))
        except (TypeError, ValueError):
            width = 3.0
        style = lt.get("style", "solid")
        dash = (
            ' stroke-dasharray="9 7"' if style == "dashed"
            else ' stroke-dasharray="2 6" stroke-linecap="round"' if style == "dotted"
            else ""
        )
        if states.get(src.code) == "maxed":
            color = (
                STATE_COLORS["maxed"]
                if states.get(dst.code) in ("maxed", "in_progress")
                else STATE_COLORS["unlockable"]
            )
        else:
            color = LINK_DIM
        out.append(
            f'<line x1="{src.position.x}" y1="{src.position.y}" x2="{dst.position.x}" '
            f'y2="{dst.position.y}" stroke="{color}" stroke-width="{width:g}"{dash}/>'
        )
    return "".join(out)


def _render_node(
    definition: SkillTreeDefinition,
    node: SkillNode,
    state: str,
    level: int,
    show_icon: bool,
    ui: float = 1.0,
) -> str:
    shape = _shape_of(definition, node)
    geometry = shape.get("geometry", "circle")
    size = _size_of(definition, node)
    frame = STATE_COLORS.get(state, STATE_COLORS["locked"])
    locked = state == "locked"
    fill = LOCKED_FILL if locked else _type_color(definition, node)
    stroke_w = 1.5 if locked else 3.5

    parts: list[str] = []
    # Zone de clic plus large que la case (doigts, petites cases).
    parts.append(f'<circle r="{size + 10:.0f}" fill="transparent"/>')
    if state == "maxed":
        parts.append(_shape(geometry, size + 6, f'fill="{frame}" fill-opacity="0.35"'))
    if shape.get("ring"):
        parts.append(_shape(
            geometry, size + 5,
            f'fill="none" stroke="{frame}" stroke-opacity="0.7" stroke-width="2"',
        ))
    parts.append(_shape(
        geometry, size, f'fill="{fill}" stroke="{frame}" stroke-width="{stroke_w}"',
    ))
    if show_icon and node.icon:
        grey = ' filter="url(#f-grey)" opacity="0.4"' if locked else ""
        parts.append(
            f'<text text-anchor="middle" dominant-baseline="central" y="{size * 0.06:.1f}" '
            f'font-size="{size * 1.05:.1f}" font-family="{EMOJI_FONT}"{grey}>'
            f"{escape(node.icon)}</text>"
        )

    badge = not node.start and node.max_level > 1
    if badge:
        bw, bh = 34 * ui, 16 * ui
        parts.append(
            f'<rect x="{-bw / 2}" y="{size - bh / 2:.1f}" width="{bw}" height="{bh}" '
            f'rx="{bh / 2}" fill="{BACKGROUND}" stroke="{frame}" stroke-width="1.2"/>'
            f'<text text-anchor="middle" dominant-baseline="central" y="{size:.1f}" '
            f'font-family="{FONT}" font-size="{11 * ui:.1f}" font-weight="700" fill="#ffffff">'
            f"{min(level, node.max_level)}/{node.max_level}</text>"
        )
    label_y = size + (bh / 2 + 15 * ui if badge else 17 * ui)
    # Contour puis texte, en DEUX passes : cairosvg ignore `paint-order`, il
    # peindrait le contour par-dessus les lettres.
    label = escape(node.name or node.code)
    common = (
        f'text-anchor="middle" y="{label_y:.1f}" font-family="{FONT}" '
        f'font-size="{13 * ui:.1f}" font-weight="700"'
    )
    parts.append(
        f'<text {common} fill="{COLORS["label_outline"]}" '
        f'stroke="{COLORS["label_outline"]}" stroke-width="{3.5 * ui:.1f}" '
        f'stroke-linejoin="round">{label}</text>'
        f'<text {common} fill="{COLORS["label"]}"'
        f'{" opacity=\"0.55\"" if locked else ""}>{label}</text>'
    )

    data = (
        f'data-code="{escape(node.code)}" data-name="{escape(node.name)}" '
        f'data-description="{escape(node.description)}" data-state="{state}" '
        f'data-level="{level}" data-max-level="{node.max_level}"'
    )
    # Deux <g> : le wrapper porte la position, l'intérieur reçoit le zoom CSS
    # du survol sur le web (sinon le transform du survol écrase la position).
    return (
        f'<g transform="translate({node.position.x}, {node.position.y})">'
        f'<g class="skill-node skill-node--{state}" {data}>{"".join(parts)}</g></g>'
    )


def _states(state: SkillTreeState, definition: SkillTreeDefinition) -> dict[str, str]:
    service = SkillTreeService(definition)
    return {
        code: service.compute_node_state(state.allocations, code)
        for code in definition.skills
    }


def _display_level(state: SkillTreeState, node: SkillNode) -> int:
    return node.max_level if node.start else state.allocations.get(node.code, 0)


def render_to_svg(
    state: SkillTreeState,
    definition: SkillTreeDefinition,
    focus: bool = True,
    icons_in_svg: bool = True,
    view_box: tuple[float, float, float, float] | None = None,
    ui_scale: float = 1.0,
    header: bool = True,
) -> str:
    """Construit le SVG entier (à inliner dans une page ou convertir en PNG).

    `focus` est conservé pour compatibilité : l'arbre de la saison 1 tient en
    entier dans une image lisible, on montre donc toujours tout l'arbre.
    `icons_in_svg=False` : n'inclut PAS les emojis (cairosvg ne sait pas rendre
    les emojis couleur) — le PNG les recompose ensuite via Pillow.
    """
    states = _states(state, definition)
    vx, vy, vw, vh = view_box or _compute_view_box(definition, header=header)
    mx, my, mw, mh = main_tree_view_box(definition)
    bg_defs, background = _render_background(definition, states)
    nodes = "".join(
        _render_node(
            definition, node, states[node.code], _display_level(state, node),
            show_icon=icons_in_svg, ui=ui_scale,
        )
        for node in definition.skills.values()
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vx} {vy} {vw} {vh}" '
        f'preserveAspectRatio="xMidYMid meet" data-main-view="{mx} {my} {mw} {mh}">'
        f'<defs>{bg_defs}<filter id="f-grey"><feColorMatrix type="saturate" values="0"/>'
        f"</filter></defs>"
        f'<rect x="{vx}" y="{vy}" width="{vw}" height="{vh}" fill="{BACKGROUND}"/>'
        f"{background}"
        f"{_render_edges(definition, states)}"
        f"{nodes}"
        f"{_render_header(state, vx, vy, vw, ui_scale) if header else ''}"
        f"</svg>"
    )


def render_to_png(
    state: SkillTreeState,
    definition: SkillTreeDefinition,
    width: int = 1600,
    height: int | None = None,
) -> bytes:
    """PNG pour Discord : SVG rendu par cairosvg, puis emojis recomposés par
    Pillow (cairo ne sait pas dessiner les emojis couleur → carrés vides).

    La hauteur suit les proportions de l'arbre (bornée), pour ne pas noyer un
    arbre large dans du vide.
    """
    import io

    from PIL import Image

    from app.bot.rendering.emoji_text import draw_text_with_emojis
    from app.bot.rendering.pillow_utils import try_font

    vx, vy, vw, vh = _compute_view_box(definition)
    if height is None:
        height = int(max(560, min(1700, width * vh / vw)))
    scale = min(width / vw, height / vh)
    # Image réduite : noms et badges grossis pour rester lisibles dans Discord.
    ui_scale = max(1.0, min(1.8, 0.85 / scale))
    svg = render_to_svg(
        state, definition, icons_in_svg=False, view_box=(vx, vy, vw, vh),
        ui_scale=ui_scale,
    )
    png = cairosvg.svg2png(
        bytestring=svg.encode("utf-8"), output_width=width, output_height=height,
    )
    img = Image.open(io.BytesIO(png)).convert("RGBA")

    off_x = (width - vw * scale) / 2
    off_y = (height - vh * scale) / 2
    states = _states(state, definition)

    for node in definition.skills.values():
        if not node.icon:
            continue
        px = max(12, int(_size_of(definition, node) * 1.05 * scale))
        cx = off_x + (node.position.x - vx) * scale
        cy = off_y + (node.position.y - vy) * scale
        layer = Image.new("RGBA", (px * 2, px * 2), (0, 0, 0, 0))
        draw_text_with_emojis(
            layer, (px // 2, px // 2), node.icon, try_font(px),
            fill=(255, 255, 255, 245), shadow=(0, 0, 0, 0), emoji_size=px,
        )
        if states.get(node.code) == "locked":
            # Case verrouillée : icône en noir et blanc, atténuée.
            alpha = layer.getchannel("A").point(lambda a: int(a * 0.45))
            layer = Image.merge("RGBA", (*[layer.convert("L")] * 3, alpha))
        img.alpha_composite(layer, (int(cx - px), int(cy - px)))

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()
