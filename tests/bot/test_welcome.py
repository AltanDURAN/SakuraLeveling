"""Accueil d'un nouveau membre : carte illustrée + message court (31/10/2026)
qui n'envoie qu'au règlement — le seul salon qu'un nouveau venu voit avec
l'accueil (parcours d'arrivée, 08/11/2026)."""

import io

from PIL import Image

from app.bot.cogs.onboarding_cog import JOURNEY, WELCOME_IMAGE, build_join_embed, build_join_view
from app.bot.rendering.welcome_card import HEIGHT, WIDTH, compose_welcome_card
from app.infrastructure.config.settings import settings


def test_la_carte_se_dessine_meme_sans_avatar():
    png = compose_welcome_card("Un nom vraiment très très long pour une carte de bienvenue", None, 1234)
    assert Image.open(io.BytesIO(png)).size == (WIDTH, HEIGHT)


def test_message_d_arrivee():
    embed = build_join_embed("<@42>")
    assert "<@42>" in embed.description and f"<#{settings.rules_channel_id}>" in embed.description
    # Le salon du tutoriel n'est pas encore visible : il s'afficherait « sans accès ».
    assert f"<#{settings.tutorial_channel_id}>" not in embed.description
    assert "Rang F" in embed.description and embed.footer.text == JOURNEY
    assert embed.image.url == f"attachment://{WELCOME_IMAGE}"
    urls = [b.url for b in build_join_view(7).children]
    assert urls == [f"https://discord.com/channels/7/{settings.rules_channel_id}"]


def test_qui_revient_retrouve_ses_salons():
    embed = build_join_embed("<@42>", returning=True)
    assert "Bon retour" in embed.description and "accepte-le" not in embed.description
