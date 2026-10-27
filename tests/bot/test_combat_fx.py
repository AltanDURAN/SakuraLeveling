"""Rendu des chiffres et effets de combat (`combat_fx`) : tailles bornées,
chaque type d'événement se dessine, et une cible absente ou au bord du cadre
ne casse rien."""

from PIL import Image

from app.bot.rendering import combat_fx
from app.bot.rendering.fight_scene import FRAME_H, FRAME_W, render_scene


def test_la_taille_suit_la_part_des_pv_entre_un_minimum_et_un_maximum():
    sizes = [combat_fx.number_size(a, 1000) for a in (0, 50, 150, 300, 5000)]
    assert sizes == sorted(sizes) and sizes[0] == combat_fx.MIN_SIZE and sizes[-1] == combat_fx.MAX_SIZE
    assert combat_fx.number_size(300, 1000, crit=True) > combat_fx.number_size(300, 1000)


def test_chaque_evenement_se_dessine():
    anchors = {"e0": combat_fx.Anchor(300, 400, 400, 600, 1000, "feu", "loup_sacre"),
               "p1": combat_fx.Anchor(500, 1210, 88, 88, 500, player=True)}
    kinds = [("hit", "e0", "slash"), ("crit", "e0", "storm"), ("hit", "p1", "melee"), ("hit", "p1", "aoe"),
             ("heal", "p1", ""), ("shield", "p1", ""), ("block", "p1", ""), ("dodge", "e0", ""),
             ("dot", "e0", "poison"), ("dot", "p1", "burn"), ("stun", "e0", "freeze"), ("ko", "p1", ""),
             ("revive", "p1", ""), ("execute", "e0", ""), ("recoil", "e0", ""), ("immune", "e0", ""),
             ("enrage", "e0", ""), ("hit", "e0", "splash"), ("hit", "e0", "fire"), ("hit", "e0", "void")]
    for kind, target, style in kinds:
        base = Image.new("RGBA", (FRAME_W, FRAME_H), (30, 30, 40, 255))
        before = base.tobytes()
        combat_fx.draw_combat_fx(base, [{"kind": kind, "target": target, "amount": 120, "source": "e0"
                                         if target == "p1" else "p1", "style": style}], anchors, seed=1)
        assert base.tobytes() != before, kind


def test_cible_absente_ou_au_bord_du_cadre():
    base = Image.new("RGBA", (FRAME_W, FRAME_H), (0, 0, 0, 255))
    combat_fx.draw_combat_fx(base, [{"kind": "hit", "target": "e9", "amount": 5}], {}, seed=0)
    edge = {"e0": combat_fx.Anchor(-200, 1100, 400, 400, 100, code="ours_colosse")}
    combat_fx.draw_combat_fx(base, [{"kind": "crit", "target": "e0", "amount": 99, "source": "p1"}], edge)


def test_la_scene_porte_les_chiffres_du_tour():
    mob = {"code": "x", "name": "Monstre", "image_name": "", "element": "feu", "current_hp": 50, "max_hp": 100}
    players = [{"player_id": 1, "name": "A", "avatar_url": None, "current_hp": 80, "max_hp": 100}]
    plain = render_scene(mob=mob, players=players)
    hit = render_scene(mob=mob, players=players, fx_seed=3,
                       events=[{"kind": "crit", "target": "e0", "amount": 40, "source": "p1", "style": "slash"},
                               {"kind": "heal", "target": "p1", "amount": 20, "source": "p1"}])
    assert plain.tobytes() != hit.tobytes()
