"""La pièce d'or, monnaie du jeu (08/11/2026) : emoji de l'application sur
Discord, et la pièce dessinée à la place de 💰 / 🪙 dans les images du bot."""

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

import discord
from PIL import Image

from app.bot.embeds.daily_embeds import build_daily_success_embed
from app.bot.embeds.tower_embeds import _reward_text
from app.bot.rendering import emoji_text
from app.bot.views.trade_draft_view import TradeDraftView
from app.shared.enums import GOLD_EMOJI
from app.shared.paths import GOLD_COIN_IMAGE

BOT_DIR = Path(__file__).resolve().parents[2] / "app" / "bot"


def test_c_est_l_emoji_de_l_application():
    emoji = discord.PartialEmoji.from_str(GOLD_EMOJI)
    assert (emoji.name, emoji.id, emoji.animated) == ("piece_or", 1568912634672185405, False)


def test_la_piece_est_detouree():
    with Image.open(GOLD_COIN_IMAGE) as coin:
        assert coin.mode == "RGBA" and coin.width == coin.height
        assert coin.getpixel((0, 0))[3] == 0                         # coin du carré : transparent
        assert coin.getpixel((coin.width // 2, coin.height // 2))[3] == 255


def test_les_images_dessinent_la_piece(monkeypatch):
    emoji_text._render_emoji_cached.cache_clear()
    monkeypatch.setattr(emoji_text, "_EMOJI_FONT", None)              # même sans la police emoji
    try:
        with Image.open(GOLD_COIN_IMAGE) as coin:
            expected = coin.convert("RGBA").resize((40, 40), Image.Resampling.LANCZOS).tobytes()
        assert emoji_text._render_emoji_cached("💰", 40).tobytes() == expected
        assert emoji_text._render_emoji_cached("🪙", 40).tobytes() == expected
    finally:
        emoji_text._render_emoji_cached.cache_clear()


def test_les_montants_d_or_portent_la_piece():
    assert f"**1 500** {GOLD_EMOJI}" in build_daily_success_embed(streak=3, gold_gained=1500).description
    reward = SimpleNamespace(gold=1200, xp=0, materials=[])
    assert _reward_text(reward) == f"{GOLD_EMOJI} 1 200 or"


def test_les_boutons_d_or_portent_la_piece_en_emoji():
    async def buttons():
        view = TradeDraftView(SimpleNamespace(display_name="Alice"), SimpleNamespace(display_name="Bob"))
        return {b.label: b.emoji for b in view.children if isinstance(b, discord.ui.Button)}

    found = asyncio.run(buttons())
    assert found["Mon or"].id == found["Or demandé"].id == 1568912634672185405


#: Discord y écrirait « :piece_or: » en toutes lettres au lieu de la pièce.
MISPLACED = re.compile(r'(set_footer|set_author)\(.*GOLD_EMOJI|(label|placeholder)=f"[^"]*\{GOLD_EMOJI\}')


def test_jamais_dans_un_pied_de_page_ni_dans_le_texte_d_un_bouton():
    offenders = [f"{path.relative_to(BOT_DIR)}:{number}"
                 for path in sorted(BOT_DIR.rglob("*.py"))
                 for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
                 if MISPLACED.search(line)]
    assert offenders == []
