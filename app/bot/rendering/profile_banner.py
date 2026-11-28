"""Profile complet rendu en une seule image Pillow stylée.

L'objectif : un /profile lisible d'un coup d'œil avec des emojis couleur
(via NotoColorEmoji), des couleurs d'accent par stat, et une typo
généreuse. Tout est dans l'image — l'embed Discord ne sert que de
conteneur.

Layout (1024 × 980) :
    ┌───────────────────────────────────────────────────────────┐
    │  HEADER (~310 px)                                         │
    │  Avatar (210) │ 🏷 Title • NAME • Niveau X · Classe        │
    │               │ 🟦 XP bar avec %                          │
    │               │ 💰 or  ·  💪 points  ·  📚  ·  🔥 Daily Streak│
    │                                            ┌────────────┐ │
    │                                            │  RANK BADGE│ │
    │                                            │  ⚡ PWR XXX │ │
    │                                            └────────────┘ │
    ├───────────────────────────────────────────────────────────┤
    │  ⚔ STATS DE COMBAT (~270 px)                              │
    │  4×2 grid coloré : ❤ PV | ⚔ Atk | 🛡 Def | 💨 Vit         │
    │                    🎯 Crit | 💥 Cdmg | 🌀 Esq | ✨ Régen   │
    ├───────────────────────────────────────────────────────────┤
    │  📈 STATISTIQUES DE CARRIÈRE (~280 px)                    │
    │  4×2 grid : 💀 Tués | ⚔ Combats | 💰 Or | 💢 Dmg inf      │
    │             🛡 Encaissés | 💚 Soignés | 🌀 Esquives | 🏆 V/D│
    └───────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from app.bot.rendering.emoji_text import (
    draw_text_with_emojis,
    measure_text_with_emojis,
)
from app.bot.rendering.image_utils import (
    crop_to_circle,
    download_image,
)
from app.shared.formatters import format_int
from app.bot.rendering.profile_banner_parts import (  # noqa: F401 — sortis le 28/11/2026
    COLORS,
    _add_vignette,
    _cosmetic_background,
    _draw_mythic_aura,
    _draw_panel,
    _draw_rank_badge,
    _draw_section_header,
    _draw_stat_card,
    _draw_text_with_shadow,
    _draw_title,
    _draw_xp_bar,
    _fit_classes,
    _format_compact,
    _framed_avatar,
    _rank_color,
    _try_font,
)


WIDTH = 1024
# +144 (une rangée de cards) depuis l'ajout de la ligne Mana/Régén M dans la
# grille de combat (10 cards = 3 rangées au lieu de 2).
HEIGHT = 1224
# Bloc « affinités élémentaires », ajouté à la hauteur SEULEMENT quand des
# affinités sont fournies (sinon la bannière garderait une zone vide).
AFFINITY_BLOCK_H = 178


def compose_profile_banner(
    output_path: str,
    *,
    display_name: str,
    avatar_url: str | None,
    level: int,
    xp_current: int,
    xp_required: int,
    gold: int,
    rank_label: str,
    power_score: str,
    class_name: str | None,
    stats: dict,
    career: dict | None = None,
    daily_streak: int = 0,
    skill_points: int = 0,
    stat_points: int = 0,
    active_title: str | None = None,
    #: élément → affinité 0..100. None ⇒ section masquée.
    affinities: dict[str, int] | None = None,
    #: élément → {"known", "dead", "cap", "boosts"} (talents découverts avec
    #: la voyante). Absent ⇒ talent inconnu, affiché ❓.
    affinity_talents: dict[str, dict] | None = None,
    #: Pièces mythiques portées : > 0 ⇒ aura rouge et or autour de l'avatar.
    mythic_pieces: int = 0,
    #: Cosmétiques portés : {"fond" | "cadre" | "titre": apparence} (cf. /apparence).
    cosmetics: dict | None = None,
) -> None:
    cosmetics = cosmetics or {}
    height = HEIGHT + (AFFINITY_BLOCK_H if affinities else 0)
    # Fond + pétales de sakura en filigrane — décor "anime" subtil avant tout
    # ce qui sera dessiné par-dessus. Seed dérivé du nom pour que chaque
    # profil ait sa disposition unique mais stable d'un appel à l'autre.
    bg = _cosmetic_background(WIDTH, height, cosmetics.get("fond"), seed=hash(display_name) & 0xFFFF)

    # Vignette douce dans les 4 coins pour ambiance "vue plongeante",
    # plus pro qu'un fond plat dégradé. On la rend très subtile pour
    # ne pas perdre en lisibilité au centre.
    _add_vignette(bg)

    draw = ImageDraw.Draw(bg)

    # Fonts. Tailles "grosses" pour rester lisibles même quand Discord
    # compresse la bannière en thumbnail (~400 px de large), donc la
    # plupart des joueurs verront cette taille sans cliquer.
    name_font = _try_font(64, bold=True)
    title_font = _try_font(30, bold=True)
    sub_font = _try_font(30)
    info_font = _try_font(28, bold=True)
    label_font = _try_font(24, bold=True)
    value_font = _try_font(42, bold=True)
    section_font = _try_font(30, bold=True)
    rank_font = _try_font(80, bold=True)
    pwr_inner_font_size = 24  # utilisé plus bas dans l'appel au badge
    xp_label_font = _try_font(24, bold=True)

    margin = 30

    # ----- HEADER -----
    header_y = margin
    avatar_size = 210
    avatar_x = margin + 4
    avatar_y = header_y + 24

    avatar_img = None
    if avatar_url:
        try:
            avatar_img = download_image(avatar_url)
        except Exception:
            avatar_img = None
    if avatar_img is None:
        avatar_img = Image.new("RGBA", (avatar_size, avatar_size), (60, 60, 80, 255))

    if mythic_pieces:
        _draw_mythic_aura(bg, (avatar_x + avatar_size // 2, avatar_y + avatar_size // 2),
                          avatar_size // 2)

    avatar_circle = crop_to_circle(avatar_img, avatar_size)
    # Anneau de la couleur du rang : signal visuel immédiat du tier.
    # Le rang sert deux fois (badge + ring) — cohérent et sympa.
    rc = _rank_color(rank_label)
    avatar_outlined, frame_margin = _framed_avatar(avatar_circle, rc, cosmetics.get("cadre"))
    bg.alpha_composite(avatar_outlined, (avatar_x - frame_margin, avatar_y - frame_margin))

    info_x = avatar_x + avatar_size + 30
    info_y = avatar_y - 6

    # Title (emoji éventuel) en or au-dessus du nom
    if active_title:
        _draw_title(bg, (info_x, info_y - 30), active_title, title_font, cosmetics.get("titre"))
    # Nom
    _draw_text_with_shadow(
        draw, (info_x, info_y), display_name, name_font,
    )

    # Niveau · Classe — placé sous le nom (qui fait `name_font.size` de haut)
    level_text = f"Niveau {level}"
    level_text = _fit_classes(level_text, class_name, sub_font, WIDTH - info_x - 220)
    level_y = info_y + name_font.size + 6
    _draw_text_with_shadow(
        draw, (info_x, level_y), level_text, sub_font,
        fill=COLORS["text_secondary"],
    )

    # Barres PV / Mana / XP — full width depuis info_x jusqu'au début de la
    # zone badge. PV/Mana remplacent les anciennes cards (info désormais dans
    # les barres) ; l'XP garde son style cyan historique.
    bars_x = info_x
    bar_w = WIDTH - info_x - 220
    bar_h = 28
    _seed = hash(display_name) & 0xFFFF

    def _labeled_bar(y, ratio, text, text_color, fill_start, fill_end, glow):
        _draw_xp_bar(
            bg, (bars_x, y), (bar_w, bar_h), ratio, seed=_seed,
            fill_start=fill_start, fill_end=fill_end, glow_color=glow,
        )
        draw_text_with_emojis(
            bg, (bars_x, y + bar_h + 5), text, xp_label_font, fill=text_color,
        )
        return y + bar_h + 5 + xp_label_font.size + 12

    cur_bar_y = level_y + sub_font.size + 14

    # --- PV (rouge) ---
    hp_max = int(stats.get("max_hp", 0)) or 1
    hp_cur = int(stats.get("current_hp", hp_max))
    hp_regen = int(stats.get("hp_regeneration", 0))
    hp_text = f"❤️ PV : {format_int(hp_cur)} / {format_int(hp_max)}"
    if hp_regen:
        hp_text += f"  (+{hp_regen}/min)"
    cur_bar_y = _labeled_bar(
        cur_bar_y, hp_cur / hp_max, hp_text, (255, 150, 160, 255),
        (200, 50, 60), (255, 110, 120), (255, 90, 90),
    )

    # --- Mana (bleu) ---
    mana_max = int(stats.get("mana_max", 0)) or 1
    mana_cur = int(stats.get("current_mana", mana_max))
    mana_regen = int(stats.get("mana_regeneration", 0))
    mana_text = f"🔷 Mana : {format_int(mana_cur)} / {format_int(mana_max)}"
    if mana_regen:
        mana_text += f"  (+{mana_regen}/min)"
    cur_bar_y = _labeled_bar(
        cur_bar_y, mana_cur / mana_max, mana_text, (150, 190, 255, 255),
        (60, 110, 235), (120, 180, 255), (110, 160, 255),
    )

    # --- XP (cyan, style historique) ---
    raw_progress = (xp_current / xp_required) if xp_required > 0 else 0.0
    xp_progress = min(1.0, max(0.0, raw_progress))
    pct = int(round(xp_progress * 100))
    if xp_required > 0:
        xp_text = f"⚡ XP : {format_int(xp_current)} / {format_int(xp_required)}  ({pct}%)"
    else:
        xp_text = f"⚡ XP : {format_int(xp_current)}"
    cur_bar_y = _labeled_bar(
        cur_bar_y, xp_progress, xp_text, (206, 150, 255, 255),
        (150, 70, 225), (206, 130, 255), (190, 120, 255),
    )

    # Ligne d'infos compactes (or, points à dépenser, daily streak)
    bottom_info_y = cur_bar_y + 2
    parts: list[tuple[str, tuple[int, int, int, int]]] = [
        (f"💰 {_format_compact(gold)} or", COLORS["gold_color"]),
    ]
    # Points à dépenser juste après l'or : c'est ce qui doit sauter aux yeux
    # après un niveau (la ligne est limitée à deux rangées, la fin peut sauter).
    if stat_points > 0:
        parts.append((f"💪 {stat_points} pt(s) de stats", (255, 214, 120, 255)))
    if skill_points > 0:
        parts.append((f"📚 {skill_points} pt(s) d'arbre", (180, 230, 220, 255)))
    if daily_streak > 0:
        parts.append((f"🔥 Daily Streak : {daily_streak}", (255, 170, 90, 255)))

    # Wrap automatique sur 2 lignes max — pour ne pas rentrer dans la
    # zone du badge à droite et garder tout lisible.
    badge_left_edge = WIDTH - 170 - margin - 4 - 20
    info_max_x = badge_left_edge
    line_height = info_font.size + 12
    cur_x = info_x
    cur_y = bottom_info_y
    second_line_started = False
    for text, color in parts:
        next_w = measure_text_with_emojis(text, info_font, info_font.size)
        # Si ça dépasse la limite à droite, on passe à la 2e ligne.
        if cur_x + next_w > info_max_x:
            if second_line_started:
                # 3e ligne refusée — on s'arrête (l'ordre de `parts` fait la priorité)
                break
            cur_x = info_x
            cur_y += line_height
            second_line_started = True
            # Si même seul sur la 2e ligne ça déborde encore, on coupe.
            if cur_x + next_w > info_max_x:
                continue
        draw_text_with_emojis(
            bg, (cur_x, cur_y), text, info_font, fill=color,
        )
        cur_x += next_w + 24
    bottom_info_end_y = cur_y + line_height  # pour positionner la section combat

    # Badge de rang à droite — la lettre + le PWR sont DANS le badge
    # pour ne pas déborder sur la ligne d'infos juste en dessous.
    badge_size = 200
    badge_x = WIDTH - badge_size - margin - 4
    badge_y = avatar_y - 14
    pwr_inner_font = _try_font(pwr_inner_font_size, bold=True)
    _draw_rank_badge(
        bg, (badge_x, badge_y), badge_size,
        rank_label, power_score, rank_font, pwr_inner_font,
    )

    # ----- COMBAT SECTION -----
    section_combat_y = max(bottom_info_end_y + 30, badge_y + badge_size + 30)
    _draw_section_header(
        bg, (margin, section_combat_y), "⚔️  STATS DE COMBAT",
        section_font, WIDTH - 2 * margin,
    )
    combat_grid_y = section_combat_y + 56
    grid_cols = 4
    spacing = 14
    available = WIDTH - 2 * margin - spacing * (grid_cols - 1)
    card_w = available // grid_cols
    card_h = 130

    # PV / Mana / Régén sont désormais dans les barres du header — on ne
    # garde ici que les stats de combat "pures". Grille 3 colonnes
    # (6 cards = 2 rangées pleines et équilibrées).
    combat_cols = 3
    combat_available = WIDTH - 2 * margin - spacing * (combat_cols - 1)
    combat_card_w = combat_available // combat_cols
    combat_cards = [
        ("⚔️", "Attaque", _format_compact(int(stats.get("attack", 0))), "atk"),
        ("🛡️", "Défense", _format_compact(int(stats.get("defense", 0))), "def"),
        ("💨", "Vitesse", str(stats.get("speed", 0)), "speed"),
        ("🎯", "Crit %", f"{int(stats.get('crit_chance', 0))}%", "crit_chance"),
        ("💥", "Crit dmg", f"{int(stats.get('crit_damage', 100))}%", "crit_damage"),
        ("🌀", "Esquive", f"{int(stats.get('dodge', 0))}%", "dodge"),
    ]

    for idx, (emoji, label, value, accent_key) in enumerate(combat_cards):
        row = idx // combat_cols
        col = idx % combat_cols
        x = margin + col * (combat_card_w + spacing)
        y = combat_grid_y + row * (card_h + spacing)
        _draw_stat_card(
            bg, (x, y), (combat_card_w, card_h),
            emoji, label, value, label_font, value_font,
            accent_key=accent_key,
        )

    # ----- CAREER SECTION -----
    # Nombre de rangées de la grille de combat (dynamique : dépend du nombre
    # de cards, ex. 10 cards / 4 colonnes = 3 rangées).
    combat_rows = -(-len(combat_cards) // combat_cols)  # ceil division
    section_career_y = combat_grid_y + combat_rows * (card_h + spacing) + 20
    _draw_section_header(
        bg, (margin, section_career_y), "📈  STATISTIQUES DE CARRIÈRE",
        section_font, WIDTH - 2 * margin,
    )
    career_grid_y = section_career_y + 50
    career = career or {}
    fought = int(career.get("combats_fought", 0))
    won = int(career.get("combats_won", 0))
    # Le %W est volontairement omis — la card V/D voisine montre
    # déjà "87V / 20D" donc le ratio est calculable d'un coup d'œil.

    # Labels courts pour rester DANS la largeur des cards (~225 px) avec
    # value_font 40 + label_font 22. "Dégâts encaissés" est trop long, on
    # raccourcit à "Dégâts subis" ; on supprime "totales" sur "Esquives"
    # (déjà dans la section "carrière" donc implicite).
    # Toutes les valeurs en compact (1.2K, 22K, 1.5M…) — assure que les
    # chiffres tiennent dans la card à value_font 42, même quand un joueur
    # accumule des millions de dégâts ou d'or.
    career_cards = [
        ("💀", "Tués",
         _format_compact(int(career.get("monsters_killed", 0))), "kills"),
        ("⚔️", "Combats",
         _format_compact(fought), "combats"),
        ("💰", "Or amassé",
         _format_compact(int(career.get("gold_earned_total", 0))), "gold"),
        ("💢", "Dmg inf.",
         _format_compact(int(career.get("damage_dealt_total", 0))), "dmg_dealt"),
        ("🛡️", "Dmg subis",
         _format_compact(int(career.get("damage_tanked_total", 0))), "dmg_tanked"),
        ("💚", "PV soignés",
         _format_compact(int(career.get("hp_healed_total", 0))), "healed"),
        ("🌀", "Esquives",
         _format_compact(int(career.get("dodges_total", 0))), "dodge"),
        # Winrate en pourcentage (au lieu de "87 / 20"). Plus parlant
        # d'un coup d'œil et tient toujours dans la card. Affiche "—" si
        # le joueur n'a pas encore combattu (évite division par zéro).
        ("🏆", "Winrate",
         f"{round(100 * won / fought)}%" if fought > 0 else "—",
         "trophy"),
    ]

    for idx, (emoji, label, value, accent_key) in enumerate(career_cards):
        row = idx // grid_cols
        col = idx % grid_cols
        x = margin + col * (card_w + spacing)
        y = career_grid_y + row * (card_h + spacing)
        _draw_stat_card(
            bg, (x, y), (card_w, card_h),
            emoji, label, value, label_font, value_font,
            accent_key=accent_key,
        )

    # ----- AFFINITÉS ÉLÉMENTAIRES -----
    # La statistique la plus LENTE à monter du jeu (elle se farme en essences) :
    # elle mérite d'être visible à chaque /profil, pas seulement via /affinites.
    if affinities:
        from app.bot.rendering.element_visuals import ELEMENT_COLORS
        from app.shared.enums import ALL_ELEMENTS, ELEMENT_EMOJIS, ELEMENT_LABELS

        career_rows = -(-len(career_cards) // grid_cols)
        aff_section_y = career_grid_y + career_rows * (card_h + spacing) + 20
        talents_meta = affinity_talents or {}
        any_unknown = any(
            not talents_meta.get(e.value, {}).get("known") for e in ALL_ELEMENTS
        )
        _draw_section_header(
            bg, (margin, aff_section_y), "✨  AFFINITÉS ÉLÉMENTAIRES",
            section_font, WIDTH - 2 * margin,
        )
        if any_unknown:
            # Le talent caché doit donner envie : on dit où le découvrir.
            hint_font = _try_font(17, bold=False)
            hint = "❓ talent inconnu → la voyante (/voyante)"
            hint_w = ImageDraw.Draw(bg).textlength(hint, font=hint_font) + 10
            draw_text_with_emojis(
                bg, (int(WIDTH - margin - hint_w), aff_section_y + 12), hint,
                hint_font, fill=(196, 186, 220, 255), emoji_size=16,
            )
        aff_y = aff_section_y + 50
        elements = [e.value if hasattr(e, "value") else str(e) for e in ALL_ELEMENTS]
        cols = 4
        cell_w = (WIDTH - 2 * margin - (cols - 1) * spacing) // cols
        cell_h = 52
        aff_label_font = _try_font(19, bold=True)
        aff_value_font = _try_font(19, bold=True)

        for idx, element in enumerate(elements[:8]):
            meta = talents_meta.get(element, {})
            known = bool(meta.get("known"))
            cap = int(meta.get("cap", 100)) if known else 100
            value = max(0, min(max(cap, 100), int(affinities.get(element, 0))))
            row, col = divmod(idx, cols)
            x = margin + col * (cell_w + spacing)
            y = aff_y + row * (cell_h + spacing)
            color = ELEMENT_COLORS.get(element, (150, 150, 160))

            _draw_panel(bg, (x, y), (cell_w, cell_h), radius=10)
            head = f"{ELEMENT_EMOJIS.get(element, '•')} {ELEMENT_LABELS.get(element, element)}"
            draw_text_with_emojis(
                bg, (x + 12, y + 6), head, aff_label_font,
                fill=(238, 234, 246, 255), emoji_size=18,
            )
            if known and meta.get("dead"):
                value_text = "mort"
            elif known and cap > 100:
                value_text = f"{value}/{cap}"
            else:
                value_text = f"{value}"
            marker = (
                "❓ " if not known
                else "💀 " if meta.get("dead")
                else "✨ " if meta.get("boosts") else ""
            )
            tw = ImageDraw.Draw(bg).textlength(value_text, font=aff_value_font)
            _draw_text_with_shadow(
                ImageDraw.Draw(bg), (x + cell_w - 12 - tw, y + 6),
                value_text, aff_value_font,
                fill=(*color, 255) if not meta.get("dead") else (130, 126, 140, 255),
                shadow=(0, 0, 0, 160),
            )
            if marker:
                draw_text_with_emojis(
                    bg, (int(x + cell_w - 12 - tw - 26), y + 6), marker.strip(),
                    aff_value_font, fill=(238, 234, 246, 255), emoji_size=18,
                )
            # Barre de progression vers 100 : montre le chemin restant.
            bar_x, bar_y, bar_w = x + 12, y + 34, cell_w - 24
            layer = Image.new("RGBA", bg.size, (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            d.rounded_rectangle(
                [(bar_x, bar_y), (bar_x + bar_w, bar_y + 7)],
                radius=3, fill=(58, 52, 76, 220),
            )
            filled = int(bar_w * min(value, cap) / max(cap, 1))
            if filled > 2:
                d.rounded_rectangle(
                    [(bar_x, bar_y), (bar_x + filled, bar_y + 7)],
                    radius=3, fill=(*color, 255),
                )
            bg.alpha_composite(layer)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(output_path, "PNG", optimize=True)


def compose_cosmetic_preview(
    output_path: str,
    *,
    display_name: str,
    avatar_url: str | None,
    title: str | None,
    rank_label: str = "",
    cosmetics: dict | None = None,
) -> None:
    """Aperçu de l'apparence (/apparence) : le haut de la bannière seulement."""
    cosmetics = cosmetics or {}
    width, height = WIDTH, 300
    bg = _cosmetic_background(width, height, cosmetics.get("fond"), seed=hash(display_name) & 0xFFFF)
    _add_vignette(bg)
    draw = ImageDraw.Draw(bg)
    avatar_size, ax, ay = 210, 34, 45
    avatar_img = None
    if avatar_url:
        try:
            avatar_img = download_image(avatar_url)
        except Exception:
            avatar_img = None
    if avatar_img is None:
        avatar_img = Image.new("RGBA", (avatar_size, avatar_size), (60, 60, 80, 255))
    framed, margin = _framed_avatar(crop_to_circle(avatar_img, avatar_size), _rank_color(rank_label),
                                    cosmetics.get("cadre"))
    bg.alpha_composite(framed, (ax - margin, ay - margin))
    info_x = ax + avatar_size + 36
    _draw_title(bg, (info_x, 95), title or "Ton titre ici", _try_font(30, bold=True), cosmetics.get("titre"))
    _draw_text_with_shadow(draw, (info_x, 130), display_name, _try_font(64, bold=True))
    bg.convert("RGB").save(output_path, format="PNG")
