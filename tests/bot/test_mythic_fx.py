"""Visuels des pièces mythiques : cadre animé (GIF) et aura du profil."""

from PIL import Image

from app.bot.rendering.item_card_grid import CardSpec, compose_card_grid_page
from app.bot.rendering.mythic_fx import FRAMES, _perimeter_point, save_mythic_gif


def test_le_contour_suit_les_coins_arrondis():
    w, h, r = 100, 50, 16
    for i in range(200):
        x, y = _perimeter_point(w, h, i / 200, r)
        assert -0.01 <= x <= w + 0.01 and -0.01 <= y <= h + 0.01
        # Dans un coin, le point reste sur l'arc (jamais sur l'angle vif).
        for cx, cy in ((r, r), (w - r, r), (r, h - r), (w - r, h - r)):
            in_corner = (x < r or x > w - r) and (y < r or y > h - r)
            if in_corner and abs(x - cx) <= r and abs(y - cy) <= r:
                assert abs(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 - r) < 0.5


def test_gif_anime(tmp_path):
    base = Image.new("RGBA", (300, 200), (30, 30, 60, 255))
    path = save_mythic_gif(base, [(20, 20, 200, 80)], str(tmp_path / "x.png"))
    assert path.endswith(".gif")
    im = Image.open(path)
    assert im.n_frames == FRAMES and im.info.get("loop") == 0


def test_une_page_avec_mythique_devient_un_gif(tmp_path):
    plain = compose_card_grid_page(str(tmp_path / "a.png"), "T", "S", [CardSpec(name="A")])
    mythic = compose_card_grid_page(str(tmp_path / "b.png"), "T", "S",
                                    [CardSpec(name="A"), CardSpec(name="B", mythic=True)])
    assert plain.endswith(".png") and mythic.endswith(".gif")


def test_aura_du_profil(tmp_path):
    from app.bot.rendering.profile_banner import compose_profile_banner

    st = dict(max_hp=100, current_hp=100, attack=10, defense=10, speed=5, crit_chance=0,
              crit_damage=100, dodge=0, hp_regeneration=0, mana_max=100, current_mana=100,
              mana_regeneration=5)
    kw = dict(display_name="X", avatar_url=None, level=1, xp_current=0, xp_required=10,
              gold=0, rank_label="F", power_score="1", class_name=None, stats=st)
    compose_profile_banner(str(tmp_path / "a.png"), **kw)
    compose_profile_banner(str(tmp_path / "b.png"), mythic_pieces=1, **kw)
    a, b = Image.open(tmp_path / "a.png").convert("RGB"), Image.open(tmp_path / "b.png").convert("RGB")
    # Le halo rougit le pourtour de l'avatar.
    pa, pb = a.getpixel((20, 160)), b.getpixel((20, 160))
    assert pb[0] > pa[0] + 40
