"""Rendu de l'arbre de compétences en SVG (et PNG via cairosvg).

Module partagé entre la commande Discord /skill (PNG embarqué) et la page web
(SVG inline). Code pur Python + chaînes : pas de dépendance à un framework
graphique côté domain. La couleur d'un nœud dépend de son état dans l'arbre :
gris (verrouillé), bleu vif (débloquable), or (en cours), violet (max).
"""

from __future__ import annotations

from html import escape

import cairosvg

from app.application.use_cases.get_skill_tree_state import SkillTreeState
from app.domain.entities.skill_node import SkillNode
from app.domain.entities.skill_tree_definition import SkillTreeDefinition
from app.domain.services.skill_tree_service import SkillTreeService


# ----- Constantes visuelles -----

NODE_RADIUS = 36
NODE_INNER_RADIUS = 30
PADDING = 80
HEADER_HEIGHT = 100

COLORS = {
    "background_top": "#1a1a2e",
    "background_bottom": "#16213e",
    "header_text": "#e8e8f0",
    "subheader_text": "#a0a0c0",
    "edge_locked": "#3a3a4e",
    # Edge "rouge" = on doit d'abord investir dans le parent avant que cet
    # enfant soit accessible. Visuellement saillant pour guider le joueur.
    "edge_blocked_by_prereq": "#c84a4a",
    "edge_unlockable": "#4a90e2",
    "edge_in_progress": "#d4af37",
    "edge_maxed": "#9b59b6",
    "node_locked_fill": "#2a2a3e",
    "node_locked_stroke": "#4a4a5e",
    "node_locked_text": "#5a5a7a",
    "node_unlockable_fill": "#1e3a5f",
    "node_unlockable_stroke": "#4a90e2",
    "node_unlockable_text": "#e8e8f0",
    "node_in_progress_fill": "#3a2e1a",
    "node_in_progress_stroke": "#d4af37",
    "node_in_progress_text": "#fff5d4",
    "node_maxed_fill": "#3a1a3e",
    "node_maxed_stroke": "#9b59b6",
    "node_maxed_text": "#e8d4f0",
}


def _node_state_colors(state: str) -> tuple[str, str, str]:
    """Renvoie (fill, stroke, text) pour un état de nœud."""
    if state == "maxed":
        return (
            COLORS["node_maxed_fill"],
            COLORS["node_maxed_stroke"],
            COLORS["node_maxed_text"],
        )
    if state == "in_progress":
        return (
            COLORS["node_in_progress_fill"],
            COLORS["node_in_progress_stroke"],
            COLORS["node_in_progress_text"],
        )
    if state == "unlockable":
        return (
            COLORS["node_unlockable_fill"],
            COLORS["node_unlockable_stroke"],
            COLORS["node_unlockable_text"],
        )
    return (
        COLORS["node_locked_fill"],
        COLORS["node_locked_stroke"],
        COLORS["node_locked_text"],
    )


def _edge_color(child_state: str, parent_maxed: bool) -> str:
    """Couleur d'une arête (parent → enfant).

    Règle V2 : un nœud n'est améliorable que si la case précédente est
    COMPLÈTEMENT maxée. Donc tant que le parent n'est PAS maxé, le lien vers
    l'enfant est ROUGE (case inaccessible). Une fois le parent maxé, le lien
    prend la couleur progressive selon l'état de l'enfant.
    """
    if not parent_maxed:
        return COLORS["edge_blocked_by_prereq"]
    if child_state == "maxed":
        return COLORS["edge_maxed"]
    if child_state == "in_progress":
        return COLORS["edge_in_progress"]
    # parent maxé → enfant au minimum débloquable
    return COLORS["edge_unlockable"]


# Taille du cadre "focus" (unités SVG) : on ne montre qu'une PORTION de l'arbre
# autour de la zone d'action du joueur, à une échelle assez grande pour que les
# cases restent lisibles (au lieu de comprimer les 148 nœuds en timbres-poste).
FOCUS_WINDOW = 1900


def _compute_view_box_full(definition: SkillTreeDefinition) -> tuple[int, int, int, int]:
    """ViewBox englobant TOUT l'arbre (vue d'ensemble — pour le web zoomable)."""
    xs = [n.position.x for n in definition.skills.values()]
    ys = [n.position.y for n in definition.skills.values()]
    min_x = min(xs) - PADDING
    max_x = max(xs) + PADDING
    min_y = min(ys) - PADDING - HEADER_HEIGHT
    max_y = max(ys) + PADDING
    return min_x, min_y, max_x - min_x, max_y - min_y


def _compute_view_box_focus(
    state: SkillTreeState,
    definition: SkillTreeDefinition,
) -> tuple[int, int, int, int]:
    """ViewBox CADRÉ sur la zone d'action du joueur (nœuds investis + débloquables
    + le centre pour l'orientation), à échelle fixe et lisible. Le cadre suit
    la frontière de progression : centré au début, il glisse le long du bras
    au fil des investissements."""
    service = SkillTreeService(definition)
    pts: list[tuple[int, int]] = []
    for node in definition.skills.values():
        lvl = state.allocations.get(node.code, 0)
        st = service.compute_node_state(state.allocations, node.code)
        if lvl > 0 or st == "unlockable":
            pts.append((node.position.x, node.position.y))

    root = definition.get(definition.root)
    if root is not None:
        pts.append((root.position.x, root.position.y))
    if not pts:
        pts = [(0, 0)]

    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    half = FOCUS_WINDOW / 2
    return (
        int(cx - half),
        int(cy - half - HEADER_HEIGHT),
        FOCUS_WINDOW,
        FOCUS_WINDOW + HEADER_HEIGHT,
    )


def _render_header(
    state: SkillTreeState, view_x: int, view_y: int, view_width: int
) -> str:
    """Bandeau supérieur : pseudo, points dispo / dépensés.

    Positionné en HAUT de la viewBox courante (view_y), pas en absolu — sinon
    avec le cadrage focus le texte tombe au milieu de l'arbre."""
    title = escape(f"Arbre de {state.player_display_name}")
    spent_text = escape(
        f"Points disponibles : {state.available_points}   "
        f"·   Dépensés : {state.spent_points}"
    )
    cx = view_x + view_width // 2
    return f"""
        <text x="{cx}" y="{view_y + 44}"
              text-anchor="middle"
              font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
              font-size="28" font-weight="700"
              fill="{COLORS['header_text']}">{title}</text>
        <text x="{cx}" y="{view_y + 74}"
              text-anchor="middle"
              font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
              font-size="16" font-weight="500"
              fill="{COLORS['subheader_text']}">{spent_text}</text>
    """


def _render_node(
    node: SkillNode,
    state: str,
    current_level: int,
    show_icon: bool = True,
) -> str:
    fill, stroke, text_color = _node_state_colors(state)
    cx = node.position.x
    cy = node.position.y
    icon = escape(node.icon or "•")

    # Niveau affiché : "3/5" ou "" pour la racine
    level_label = (
        f"{current_level}/{node.max_level}" if node.max_level > 0 else ""
    )

    # data-* attributs pour que le JS du site puisse récupérer les détails au hover
    data_attrs = (
        f'data-code="{escape(node.code)}" '
        f'data-name="{escape(node.name)}" '
        f'data-description="{escape(node.description)}" '
        f'data-state="{state}" '
        f'data-level="{current_level}" '
        f'data-max-level="{node.max_level}"'
    )

    # Architecture en 2 <g> imbriqués pour éviter le conflit hover :
    #   • <g> wrapper externe : porte le `translate(cx, cy)` (positionnement
    #     stable, JAMAIS modifié au hover).
    #   • <g class="skill-node"> interne : porte les classes & data-* et
    #     reçoit le `transform: scale(1.08)` CSS au hover. Comme il n'a pas
    #     d'attribut transform initial, le CSS ne déplace plus le node vers
    #     (0,0).
    # NB : le hover JS bind sur `.skill-node` continue de marcher car les
    #      data-* sont sur l'élément interne.
    return f"""
        <g transform="translate({cx}, {cy})">
            <g class="skill-node skill-node--{state}" {data_attrs}>
                <circle r="{NODE_RADIUS + 4}" fill="black" opacity="0.35"
                        transform="translate(2, 3)"/>
                <circle r="{NODE_RADIUS}" fill="{fill}" stroke="{stroke}"
                        stroke-width="3"/>
                {f'''<text x="0" y="6" text-anchor="middle"
                      font-size="22" fill="{text_color}"
                      font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI Emoji', sans-serif">{icon}</text>''' if show_icon else ''}
                <text x="0" y="{NODE_RADIUS + 18}" text-anchor="middle"
                      font-size="12" font-weight="600" fill="{text_color}"
                      font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif">{escape(node.name)}</text>
                {f'<text x="0" y="{NODE_RADIUS + 34}" text-anchor="middle" font-size="11" fill="{text_color}" opacity="0.8" font-family="monospace">{level_label}</text>' if level_label else ''}
            </g>
        </g>
    """


def _render_edges(
    definition: SkillTreeDefinition,
    states: dict[str, str],
    allocations: dict[str, int],
) -> str:
    """Lignes reliant chaque parent à ses enfants. La couleur dépend de
    l'état de l'enfant ET du niveau du parent (rouge si prérequis non
    rempli, cf. `_edge_color`)."""
    edges: list[str] = []
    for node in definition.skills.values():
        for prereq_code in node.prerequisites:
            parent = definition.get(prereq_code)
            if parent is None:
                continue
            child_state = states.get(node.code, "locked")
            parent_maxed = allocations.get(prereq_code, 0) >= parent.max_level
            color = _edge_color(child_state, parent_maxed)
            x1, y1 = parent.position.x, parent.position.y
            x2, y2 = node.position.x, node.position.y
            edges.append(
                f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                f'stroke="{color}" stroke-width="3" stroke-linecap="round" '
                f'opacity="0.7"/>'
            )
    return "\n".join(edges)


def render_to_svg(
    state: SkillTreeState,
    definition: SkillTreeDefinition,
    focus: bool = True,
    icons_in_svg: bool = True,
) -> str:
    """Construit le SVG entier (à inliner dans une page HTML ou convertir en PNG).

    `focus=True` (défaut, image Discord) : cadre une PORTION de l'arbre autour de
    la zone d'action du joueur, à grande échelle (cases lisibles).
    `focus=False` (web zoomable) : vue d'ensemble du triskèle complet.
    `icons_in_svg=False` : n'inclut PAS les emojis (cairosvg ne sait pas rendre
    les emojis couleur → carrés vides). Le PNG les recompose ensuite via Pillow.
    """
    service = SkillTreeService(definition)
    states = {
        node.code: service.compute_node_state(state.allocations, node.code)
        for node in definition.skills.values()
    }

    if focus:
        view_x, view_y, view_w, view_h = _compute_view_box_focus(state, definition)
    else:
        view_x, view_y, view_w, view_h = _compute_view_box_full(definition)
    header = _render_header(state, view_x, view_y, view_w)
    edges = _render_edges(definition, states, state.allocations)
    nodes = "\n".join(
        _render_node(
            node=node,
            state=states[node.code],
            current_level=state.allocations.get(node.code, 0),
            show_icon=icons_in_svg,
        )
        for node in definition.skills.values()
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg"
        viewBox="{view_x} {view_y} {view_w} {view_h}"
        preserveAspectRatio="xMidYMid meet">
        <defs>
            <linearGradient id="bg-gradient" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" stop-color="{COLORS['background_top']}"/>
                <stop offset="100%" stop-color="{COLORS['background_bottom']}"/>
            </linearGradient>
        </defs>
        <rect x="{view_x}" y="{view_y}" width="{view_w}" height="{view_h}"
              fill="url(#bg-gradient)"/>
        {header}
        {edges}
        {nodes}
    </svg>
    """


def render_to_png(
    state: SkillTreeState,
    definition: SkillTreeDefinition,
    width: int = 1100,
    height: int = 1150,
) -> bytes:
    """Convertit le SVG en bytes PNG via cairosvg (Discord), puis RECOMPOSE les
    emojis des nœuds avec Pillow.

    cairosvg/cairo ne savent pas rendre les emojis couleur (COLR/CBDT) → ils
    sortaient en carrés vides. On rend donc le SVG SANS les icônes, puis on
    dessine chaque emoji par-dessus via NotoColorEmoji (même chemin que les
    cards /shop et /equipement, qui eux marchent).

    Vue CADRÉE (focus) : dimensions ~carrées pour coller au cadre FOCUS_WINDOW.
    """
    import io

    from PIL import Image

    from app.bot.rendering.emoji_text import draw_text_with_emojis
    from app.bot.rendering.pillow_utils import try_font

    svg = render_to_svg(state, definition, focus=True, icons_in_svg=False)
    png = cairosvg.svg2png(
        bytestring=svg.encode("utf-8"),
        output_width=width,
        output_height=height,
    )

    img = Image.open(io.BytesIO(png)).convert("RGBA")

    # Mapping coordonnées monde (viewBox) → pixels. preserveAspectRatio
    # xMidYMid meet → échelle uniforme + centrage (letterbox).
    vx, vy, vw, vh = _compute_view_box_focus(state, definition)
    scale = min(width / vw, height / vh)
    off_x = (width - vw * scale) / 2
    off_y = (height - vh * scale) / 2

    emoji_px = max(16, int(NODE_RADIUS * scale * 1.05))
    for node in definition.skills.values():
        nx, ny = node.position.x, node.position.y
        # Ne dessine que les nœuds dans le cadre visible (+ marge).
        if not (vx - 50 <= nx <= vx + vw + 50 and vy - 50 <= ny <= vy + vh + 50):
            continue
        px = off_x + (nx - vx) * scale
        py = off_y + (ny - vy) * scale
        icon = node.icon or "•"
        draw_text_with_emojis(
            img,
            (int(px - emoji_px / 2), int(py - emoji_px / 2)),
            icon,
            try_font(emoji_px),
            fill=(255, 255, 255, 245),
            shadow=(0, 0, 0, 0),
            emoji_size=emoji_px,
        )

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()
