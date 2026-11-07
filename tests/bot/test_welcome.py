"""Accueil d'un nouveau membre : carte illustrée + message court et boutons
vers le tutoriel et la première zone (31/10/2026)."""

import io

from PIL import Image

from app.bot.cogs.onboarding_cog import WELCOME_IMAGE, build_join_embed, build_join_view
from app.bot.rendering.welcome_card import HEIGHT, WIDTH, compose_welcome_card
from app.infrastructure.config.settings import settings


def test_la_carte_se_dessine_meme_sans_avatar():
    png = compose_welcome_card("Un nom vraiment très très long pour une carte de bienvenue", None, 1234)
    assert Image.open(io.BytesIO(png)).size == (WIDTH, HEIGHT)


def test_message_d_arrivee():
    embed = build_join_embed("<@42>")
    assert "<@42>" in embed.description and f"<#{settings.tutorial_channel_id}>" in embed.description
    assert f"<#{settings.rules_channel_id}>" in embed.description          # le règlement d'abord
    assert embed.image.url == f"attachment://{WELCOME_IMAGE}"
    urls = [b.url for b in build_join_view(7).children]
    assert urls[0] == f"https://discord.com/channels/7/{settings.rules_channel_id}"
    assert f"https://discord.com/channels/7/{settings.tutorial_channel_id}" in urls
    assert len(urls) == 3
