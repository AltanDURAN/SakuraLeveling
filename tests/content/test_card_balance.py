"""Équilibre des boosters, simulé avec les vraies règles et la vraie série :
ça démarre vite, puis la traque des rares prend le relais (décisions de
l'auteur du 09/11/2026 : 2 000 or, mythique toujours brillante et jamais
fabriquée, légendaire de pitié brillant)."""

import random
import statistics

from app.bot.embeds.card_embeds import per_booster
from app.domain.services import card_service as cs
from app.infrastructure.cards import card_loader


def _album_run(rng: random.Random, pool, rarity_of, sizes, max_boosters=3000):
    """Boosters pour la moitié de l'album, puis pour l'album complet, en
    recyclant les doublons et en fabriquant la carte manquante la plus chère."""
    owned: set[str] = set()
    petals, since, half = 0, 0, None
    total = sum(sizes.values())
    for n in range(1, max_boosters + 1):
        pulls, since = cs.open_booster(pool, rng, since)
        for pull in pulls:
            if pull.code in owned:
                petals += cs.petals_for(pull.rarity, pull.brillante)
            else:
                owned.add(pull.code)
        while True:
            missing = [code for code in rarity_of if code not in owned and rarity_of[code] != "mythic"]
            if not missing:
                break
            target = max(missing, key=lambda code: cs.craft_cost(rarity_of[code]))
            if petals < cs.craft_cost(rarity_of[target]):
                break
            petals -= cs.craft_cost(rarity_of[target])
            owned.add(target)
        if half is None and len(owned) * 2 >= total:
            half = n
        if len(owned) == total:
            return half, n
    return half, max_boosters


def test_la_collection_demarre_vite_puis_se_merite():
    cards = card_loader.list_cards()
    pool = card_loader.by_rarity()
    rarity_of = {c.code: c.rarity for c in cards}
    sizes = {r: len(v) for r, v in pool.items()}
    rng = random.Random(2026)
    runs = [_album_run(rng, pool, rarity_of, sizes) for _ in range(250)]
    halves = [h for h, _ in runs]
    fulls = sorted(f for _, f in runs)
    assert statistics.median(halves) <= 15, "la moitié de l'album doit venir vite"
    median_full = statistics.median(fulls)
    assert 120 <= median_full <= 280, median_full
    # Sans fabrication de la mythique, les malchanceux vont loin : c'est voulu,
    # mais pas l'infini (l'échange reste possible).
    assert fulls[int(0.9 * len(fulls))] <= 900


def test_les_chances_par_booster():
    assert 0.24 <= per_booster("epic") <= 0.30          # une sur 4
    assert 0.055 <= per_booster("legendary") <= 0.075   # une sur 16
    assert 0.0030 <= per_booster("mythic") <= 0.0045    # une sur 260


def test_un_booster_coute_et_les_petales_suivent_la_rarete():
    assert cs.BOOSTER_PRICE == 2000
    values = [cs.PETALS[r] for r in cs.RARITIES]
    assert values == sorted(values)
