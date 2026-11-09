"""Textes des cartes à collectionner : le guide épinglé du salon, le résultat
d'une ouverture, l'album et la fiche d'une carte. Les chiffres viennent des
RÈGLES (`card_service`) : un réglage changé, le texte suit."""

from __future__ import annotations

import discord
from discord.utils import escape_markdown

from app.domain.services import card_service as cs
from app.shared.enums import GOLD_EMOJI
from app.shared.formatters import format_int

GUIDE_BANNER = ("CARTES", "Les boosters de Sorn", "Ouvre, collectionne, échange", 6161)
GUIDE_FILE = "cartes.png"
ALBUM_FILE = "album.png"
COLOR = discord.Color.from_rgb(255, 150, 195)


def _pct(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text.replace(".", ",") + " %"


def per_booster(rarity: str) -> float:
    """Chance d'avoir au moins une carte de cette rareté dans un booster."""
    normal = cs.NORMAL_RATES.get(rarity, 0) / sum(cs.NORMAL_RATES.values())
    hit = cs.HIT_RATES.get(rarity, 0) / sum(cs.HIT_RATES.values())
    return 1 - (1 - normal) ** (cs.BOOSTER_SIZE - 1) * (1 - hit)


def rarity_line(rarity: str) -> str:
    return f"{cs.CARD_RARITY_EMOJIS.get(rarity, '')} {cs.RARITY_LABELS.get(rarity, rarity)}"


def color_of(rarity: str) -> discord.Color:
    return discord.Color.from_rgb(*cs.CARD_RARITY_COLORS.get(rarity, (176, 176, 186)))


# ------------------------------------------------------------- le guide --
def build_cards_guide(footer: str) -> discord.Embed:
    price = format_int(cs.BOOSTER_PRICE)
    embed = discord.Embed(
        title="🎴 Les cartes du Grand Cerisier",
        description=(
            f"Sorn a ouvert un comptoir : des **boosters de cartes** à collectionner. "
            f"**61 cartes** — les monstres des zones, les personnages, les divinités, les world boss… "
            f"et une seule **mythique**. Chaque carte a un **petit effet** dans l'aventure dès que tu la possèdes.\n"
            f"Les ouvertures sont **publiques** : tout le salon voit tes cartes se retourner."
        ),
        color=COLOR,
    )
    embed.add_field(name="🎴 Le booster", inline=False, value=(
        f"**{cs.BOOSTER_SIZE} cartes** pour **{price} or** — le premier est **offert**. Elles se retournent de la "
        "moins rare à la plus rare : la dernière est toujours **rare ou mieux**."
    ))
    normal = " · ".join(f"{cs.RARITY_LABELS[r]} {_pct(v)}" for r, v in cs.NORMAL_RATES.items())
    hit = " · ".join(f"{cs.RARITY_LABELS[r]} {_pct(v)}" for r, v in cs.HIT_RATES.items())
    odds = " · ".join(f"{rarity_line(r)} 1 sur {round(1 / per_booster(r))}" for r in ("epic", "legendary", "mythic"))
    embed.add_field(name="🎲 Les taux", inline=False, value=(
        f"**Cartes 1 à {cs.BOOSTER_SIZE - 1}** : {normal}\n"
        f"**Carte {cs.BOOSTER_SIZE}** : {hit}\n"
        f"**Dans un booster** : {odds}"
    ))
    embed.add_field(name="✨ Brillantes et légendaire garanti", inline=False, value=(
        f"Chaque carte a **{_pct(cs.BRILLANTE_PCT)}** de chances de sortir **brillante** : même effet, pur prestige. "
        "La mythique est **toujours** brillante.\n"
        f"Un **légendaire** tombe au plus tard au **{cs.PITY_BOOSTERS}e booster** sans légendaire ni mythique — "
        "et celui-là est brillant."
    ))
    petals = " · ".join(f"{cs.RARITY_LABELS[r]} {format_int(v)}" for r, v in cs.PETALS.items())
    embed.add_field(name="🌸 Doublons et pétales", inline=False, value=(
        "Garde-les pour les **échanger** (`/echange`, `/brocante`) ou **recycle-les** en pétales depuis `/album` "
        f"(on garde toujours un exemplaire) : {petals} — ×{cs.BRILLANTE_PETAL_MULT} pour une brillante.\n"
        f"Avec des pétales, **fabrique** une carte qui te manque ({cs.CRAFT_MULT} fois son recyclage). "
        "Jamais une brillante : la mythique se tire ou s'échange."
    ))
    embed.add_field(name="⚔️ Les effets", inline=False, value=(
        "Une carte possédée (normale ou brillante, une seule fois) joue en **combat de zone** et au **world boss** — "
        "jamais à la tour, aux défis ni aux épreuves :\n"
        "• **monstre** : + dégâts et + butin contre lui ;\n"
        "• **world boss** : +10 % de dégâts contre lui et ses gardes ;\n"
        "• **personnages et divinités** : un petit bonus de leur domaine ;\n"
        "• **le Grand Cerisier** : +2 % d'or et d'XP en zone."
    ))
    embed.add_field(name="📖 L'album et les titres", inline=False, value=(
        "`/album` : ta collection page par page, avec la silhouette des cartes qui te manquent. "
        "Titres à **25, 50, 75 et 100 %** de l'album, et un titre pour l'album **tout brillant**."
    ))
    embed.add_field(name="📜 Commandes", inline=False, value=(
        "`/booster [nombre]` ici, ou les boutons ci-dessous · `/album [joueur]` · `/echange` et `/brocante` pour troquer"
    ))
    embed.set_image(url=f"attachment://{GUIDE_FILE}")
    embed.set_footer(text=footer)
    return embed


# --------------------------------------------------------- une ouverture --
def _card_line(opened) -> str:
    card = opened.card
    line = f"{cs.CARD_RARITY_EMOJIS.get(card.rarity, '')} **{escape_markdown(card.name)}**"
    if opened.brillante:
        line += " ✨"
    if opened.new:
        line += " — **NOUVELLE !**"
    elif opened.new_brillante:
        line += " — 1re brillante !"
    if opened.pity:
        line += " *(légendaire garanti)*"
    return line


def build_result_embed(name: str, result) -> discord.Embed:
    count = len(result.boosters)
    best = result.best
    title = f"🎴 {name} ouvre {'un booster' if count == 1 else f'{count} boosters'}"
    if count == 1:
        lines = [_card_line(c) for c in result.cards]
    else:
        new = [c for c in result.cards if c.new or c.new_brillante]
        top = sorted((c for c in result.cards if cs.rarity_index(c.card.rarity) >= 3 or c.brillante),
                     key=lambda c: (-cs.rarity_index(c.card.rarity), not c.brillante))
        lines = []
        shown: set[tuple[str, bool]] = set()
        for c in [*top, *new]:
            key = (c.card.code, c.brillante)
            if key not in shown:
                shown.add(key)
                lines.append(_card_line(c))
        lines = lines[:15] or ["Rien de neuf cette fois : des doublons à échanger ou à recycler."]
        counts = {r: sum(1 for c in result.cards if c.card.rarity == r) for r in cs.RARITIES}
        lines.append(" · ".join(f"{cs.CARD_RARITY_EMOJIS[r]} {n}" for r, n in counts.items() if n))
    embed = discord.Embed(title=title, description="\n".join(lines),
                          color=color_of(best.card.rarity) if best else COLOR)
    before, after = result.album_before, result.album_after
    if after is not None:
        grown = f"**{before.owned} → {after.owned}**" if after.owned > before.owned else f"**{after.owned}**"
        embed.add_field(name="📖 Album", value=f"{grown} / {after.total} · ✨ {after.brillantes}", inline=True)
    embed.add_field(name="🟠 Légendaire garanti",
                    value=f"dans {cs.boosters_before_pity(result.since_top)} booster(s) au plus tard", inline=True)
    if result.free and not result.gold_spent:
        paid = "🎁 Offert par Sorn !"
    else:
        paid = f"−**{format_int(result.gold_spent)}** {GOLD_EMOJI}" + (" (le premier offert)" if result.free else "")
        paid += f" · il te reste {format_int(result.gold_left)} {GOLD_EMOJI}"
    embed.add_field(name="Prix", value=paid, inline=True)
    if result.titles:
        embed.add_field(name="🏷️ Nouveau titre", value="\n".join(result.titles) + "\n(voir `/titre_actif`)",
                        inline=False)
    return embed


def build_mythic_announcement(mention: str, card, channel_id: int | None) -> discord.Embed:
    where = f" dans <#{channel_id}>" if channel_id else ""
    return discord.Embed(
        title="🔴 LA MYTHIQUE EST TOMBÉE !",
        description=f"{mention} vient d'ouvrir **{escape_markdown(card.name)}** ✨{where} !",
        color=color_of("mythic"),
    )


# ----------------------------------------------------------------- l'album --
def build_album_embed(owner: str, coll, chapter: str, page: int, pages: int, *, own: bool) -> discord.Embed:
    album = coll.album
    rarities = " · ".join(f"{cs.CARD_RARITY_EMOJIS[r]} {o}/{t}" for r, (o, t) in album.by_rarity.items())
    lines = [
        f"**{album.owned}/{album.total}** cartes ({album.percent} %) · ✨ {album.brillantes} brillante(s)"
        + (f" · 🌸 {format_int(coll.petals)} pétales" if own else ""),
        rarities,
    ]
    if own and coll.duplicates:
        lines.append(f"♻️ {coll.duplicates} doublon(s) → {format_int(coll.duplicate_petals)} pétales "
                     "(bouton « Recycler »)")
    if own and coll.free_booster:
        lines.append("🎁 Ton premier booster est **offert** : `/booster` dans le salon des cartes.")
    embed = discord.Embed(
        title=f"📖 Album de {owner} — {cs.CHAPTER_LABELS.get(chapter, chapter)}",
        description="\n".join(lines),
        color=COLOR,
    )
    embed.set_image(url=f"attachment://{ALBUM_FILE}")
    embed.set_footer(text=f"Page {page}/{pages} · Série 1 « Le Grand Cerisier »")
    return embed


def build_card_embed(card, coll, *, own: bool) -> discord.Embed:
    normal, brillante = coll.normal.get(card.code, 0), coll.brillante.get(card.code, 0)
    title = f"#{card.number:02d} {card.name}" + (" ✨" if brillante or card.always_brillante else "")
    embed = discord.Embed(title=title, description=f"**{cs.effect_text(card)}**\n*{card.flavor}*",
                          color=color_of(card.rarity))
    embed.add_field(name="Rareté", value=rarity_line(card.rarity), inline=True)
    embed.add_field(name=cs.CATEGORIES.get(card.category, card.category), value=card.title or "—", inline=True)
    if normal or brillante:
        held = []
        if normal:
            held.append(f"{normal} normale(s)")
        if brillante:
            held.append(f"{brillante} brillante(s)")
        embed.add_field(name="Exemplaires", value=" · ".join(held), inline=True)
    elif cs.craftable(card):
        cost = cs.craft_cost(card.rarity)
        value = f"🌸 {format_int(cost)} pétales"
        if own:
            value += f" (tu en as {format_int(coll.petals)})"
        embed.add_field(name="Fabriquer", value=value, inline=True)
    else:
        embed.add_field(name="Fabriquer", value="Jamais : elle se tire ou s'échange.", inline=True)
    embed.set_image(url="attachment://carte." + ("gif" if (brillante or card.always_brillante) else "png"))
    return embed
