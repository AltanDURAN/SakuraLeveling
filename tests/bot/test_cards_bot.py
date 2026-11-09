"""Cartes à collectionner côté Discord : textes dans les limites, images,
/inventaire sans cartes, échanges à plusieurs pages, guide épinglé."""

import asyncio
import dataclasses
import io
from types import SimpleNamespace

import discord
from PIL import Image, ImageChops, ImageStat

from app.application.use_cases.cards import BoosterResult, Collection, OpenedCard
from app.bot.embeds import card_embeds
from app.bot.rendering import card_render
from app.domain.services import card_service as cs
from app.infrastructure.cards import card_loader

CARDS = {c.code: c for c in card_loader.list_cards()}


def _size(embed: discord.Embed) -> int:
    return len(embed.title or "") + len(embed.description or "") + len(embed.footer.text or "") + sum(
        len(f.name) + len(f.value) for f in embed.fields)


def _opened(*specs):
    return [OpenedCard(CARDS[code], shiny, new, False) for code, shiny, new in specs]


def _collection(normal=None, brillante=None, petals=0) -> Collection:
    cards = card_loader.list_cards()
    normal, brillante = normal or {}, brillante or {}
    return Collection(cards, normal, brillante, cs.album(cards, normal, brillante), petals, 0, 0, True)


def test_le_guide_tient_dans_les_limites_de_discord():
    embed = card_embeds.build_cards_guide("📌 pied")
    assert _size(embed) <= 6000 and all(len(f.value) <= 1024 for f in embed.fields)
    assert "2 000 or" in embed.fields[0].value and "offert" in embed.fields[0].value
    assert "1 sur 16" in embed.fields[1].value


def test_le_resultat_d_une_ouverture():
    opened = _opened(("slime", False, True), ("zombie", False, False), ("gargouille", True, True),
                     ("borak", False, True), ("slime_titan", True, True))
    cards_ = card_loader.list_cards()
    before = cs.album(cards_, {}, {})
    after = cs.album(cards_, {"slime": 1, "zombie": 1, "borak": 1}, {"gargouille": 1, "slime_titan": 1})
    result = BoosterResult(True, boosters=[opened], gold_spent=0, free=True, gold_left=500,
                           album_before=before, album_after=after, since_top=0, titles=["🎴 Collectionneur"])
    embed = card_embeds.build_result_embed("Ana", result)
    assert "NOUVELLE" in embed.description and "Titan Visqueux** ✨" in embed.description
    assert any("Offert" in f.value for f in embed.fields)
    assert any("0 → 5" in f.value for f in embed.fields)
    many = BoosterResult(True, boosters=[opened] * 10, gold_spent=18000, free=False, gold_left=0,
                         album_before=before, album_after=after, since_top=3)
    assert _size(card_embeds.build_result_embed("Ana", many)) <= 6000


def test_album_et_fiche_d_une_carte():
    coll = _collection({"slime": 3}, {"gobelin_assassin": 1}, petals=120)
    embed = card_embeds.build_album_embed("Ana", coll, "clairiere", 1, 9, own=True)
    assert "2/61" in embed.description and "pétales" in embed.description
    other = card_embeds.build_album_embed("Ana", coll, "clairiere", 1, 9, own=False)
    assert "pétales" not in other.description
    card = card_embeds.build_card_embed(CARDS["gobelin_runique"], coll, own=True)
    assert any(f.name == "Fabriquer" for f in card.fields)
    mythic = card_embeds.build_card_embed(CARDS["grand_cerisier"], coll, own=True)
    assert any("échange" in f.value for f in mythic.fields)


def test_images_des_cartes():
    face = Image.open(io.BytesIO(card_render.card_png(CARDS["borak"])))
    assert face.size == (card_render.W, card_render.H)
    page = Image.open(io.BytesIO(card_render.compose_album_page(
        [c for c in CARDS.values() if c.chapter == "clairiere"], {"slime": 2}, {"gobelin": 1},
        "Clairière sinistre", "2/9")))
    assert page.width > 600 and page.height > 900
    opened = _opened(("slime", False, True), ("zombie", False, False), ("gargouille", True, True),
                     ("borak", False, True), ("grand_cerisier", True, True))
    gif = card_render.animate_booster(opened)
    assert gif is not None and len(gif) <= card_render.MAX_GIF_BYTES
    animation = Image.open(io.BytesIO(gif))
    assert animation.n_frames > 30
    assert card_render.animation_seconds(opened) > 3
    still = Image.open(io.BytesIO(card_render.compose_booster_result(opened)))
    assert still.size == animation.size
    assert Image.open(io.BytesIO(card_render.card_gif(CARDS["slime_titan"], frames=4))).n_frames == 4


def test_l_inventaire_ne_montre_pas_les_cartes():
    from app.bot.embeds.inventory_embeds import _is_inventory_item

    def item(category):
        return SimpleNamespace(item_definition=SimpleNamespace(category=category))
    assert _is_inventory_item(item("resource")) and _is_inventory_item(item("consumable"))
    assert not _is_inventory_item(item("carte"))


def test_les_echanges_passent_par_pages_au_dela_de_vingt_cinq_objets():
    import asyncio

    from app.bot.views.trade_draft_view import SELECT_LIMIT, _ItemSelectView, _sorted_items

    async def build():
        choices = [(f"code{i}", f"Objet {i}", 1) for i in range(60)]
        view = _ItemSelectView("Choisis", choices, lambda *a: None, lambda *a: None)
        first = [o.value for o in view.select.options]
        view.page = 2
        view._fill_select()
        return view, first
    view, first = asyncio.run(build())
    assert view.pages == 3 and len(first) == SELECT_LIMIT and first[0] == "code0"
    assert [o.value for o in view.select.options] == [f"code{i}" for i in range(50, 60)]
    assert "(3/3)" in view.select.placeholder

    def inv(name, category, rarity, quantity):
        return SimpleNamespace(quantity=quantity, item_definition=SimpleNamespace(
            name=name, category=category, rarity=rarity))
    ordered = _sorted_items([inv("Carte Slime", "carte", "common", 5), inv("Potion", "consumable", "common", 2),
                             inv("Carte Titan", "carte", "legendary", 1), inv("Gelée", "resource", "common", 9)])
    assert [i.item_definition.name for i in ordered] == ["Gelée", "Potion", "Carte Titan", "Carte Slime"]


def test_le_guide_du_salon_des_cartes_porte_les_boutons(monkeypatch):
    from app.bot.cogs import channel_guides_cog
    from app.infrastructure.config.settings import settings

    monkeypatch.setattr(settings, "gambling_channel_id", 777)
    guide = next(g for g in channel_guides_cog.current_guides() if g.channel_id == 777)
    assert guide.view is not None and guide.embed.footer.text == channel_guides_cog.guides.GUIDE_FOOTER

    async def custom_ids():
        return {item.custom_id for item in guide.view().children}
    import asyncio
    assert {"cards:open:1", "cards:open:5", "cards:open:10", "cards:album"} == asyncio.run(custom_ids())


def test_la_brillante_est_pleine_carte_holographique_et_animee():
    card = CARDS["slime_titan"]
    normal = Image.open(io.BytesIO(card_render.card_png(card))).convert("RGB")
    shiny = Image.open(io.BytesIO(card_render.card_png(card, True))).convert("RGB")
    assert normal.size == shiny.size == (card_render.W, card_render.H)
    # Pleine carte : l'illustration remplace le cadre sombre de la normale.
    band = (40, 80, card_render.W - 40, 300)
    assert sum(ImageStat.Stat(ImageChops.difference(normal.crop(band), shiny.crop(band))).mean) / 3 > 20
    frames = card_render.holo_frames(card, 4)
    assert len(frames) == 4 and frames[0].tobytes() != frames[2].tobytes(), "le foil doit bouger"
    gif = card_render.card_gif(card)
    animation = Image.open(io.BytesIO(gif))
    assert animation.n_frames == card_render.HOLO_FRAMES and animation.info.get("loop") == 0
    assert len(gif) < 4_000_000
    assert card_render.card_gif(card) is gif, "l'animation est gardée en mémoire"


def test_une_carte_modifiee_est_redessinee():
    card = CARDS["borak"]
    renamed = dataclasses.replace(card, name="Borak le Grand")
    assert card_render.render_version(card) != card_render.render_version(renamed)
    assert card_render.card_png(card) != card_render.card_png(renamed)
    assert card_render.render_version(card) == card_render.render_version(CARDS["borak"])


def test_les_boutons_et_le_guide_suivent_les_reglages(monkeypatch):
    from app.bot.views.card_views import BoosterButtons

    params = cs.CardParams(booster_price=3500, first_free=False, pity_boosters=0)
    monkeypatch.setattr(card_loader, "params", lambda: params)

    async def label():
        return BoosterButtons().open_one.label
    assert "3 500" in asyncio.run(label())
    embed = card_embeds.build_cards_guide("📌 pied")
    assert "3 500 or" in embed.fields[0].value and "offert" not in embed.fields[0].value
    assert not any("garanti" in f.name for f in embed.fields)
    assert _size(embed) <= 6000 and all(len(f.value) <= 1024 for f in embed.fields)
