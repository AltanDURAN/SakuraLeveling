"""Équilibre des boosters, simulé avec les vraies règles et la vraie série :
ça démarre vite, puis la traque des rares prend le relais (décisions de
l'auteur du 09/11/2026 : 2 000 or, mythique toujours brillante et jamais
fabriquée, légendaire de pitié brillant)."""

import random

from app.bot.embeds.card_embeds import per_booster
from app.domain.services import card_service as cs
from app.infrastructure.cards import card_loader


def test_la_collection_demarre_vite_puis_se_merite():
    sim = cs.simulate_album(card_loader.list_cards(), card_loader.params(), runs=250, rng=random.Random(2026))
    assert sim.half <= 15, "la moitié de l'album doit venir vite"
    assert 120 <= sim.full <= 280, sim.full
    # Sans fabrication de la mythique, les malchanceux vont loin : c'est voulu,
    # mais pas l'infini (l'échange reste possible).
    assert sim.full_p90 <= 900
    assert sim.capped == 0 and sim.mythic is not None


def test_les_chances_par_booster():
    assert 0.24 <= per_booster("epic") <= 0.30          # une sur 4
    assert 0.055 <= per_booster("legendary") <= 0.075   # une sur 16
    assert 0.0030 <= per_booster("mythic") <= 0.0045    # une sur 260


def test_un_booster_coute_et_les_petales_suivent_la_rarete():
    assert cs.BOOSTER_PRICE == 2000
    values = [cs.PETALS[r] for r in cs.RARITIES]
    assert values == sorted(values)
