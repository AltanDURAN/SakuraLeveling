"""Écrans du bot en image (21/11/2026) : ils se dessinent dans les pires cas
réalistes, et chaque commande retombe sur son texte si le rendu échoue."""

from PIL import Image

from app.bot.embeds.screen_embed import image_embed
from app.bot.rendering import screens

LONG = "W" * 32


def _check(path):
    with Image.open(path) as img:
        assert img.width == 1024 and 300 < img.height < 2000


def test_quetes(tmp_path):
    long_quest = screens.QuestCard("Une quête au nom vraiment très très long " * 3, "Une description " * 20, "hard",
                                   123_456, 99, 9_999_999, 9_999_999, "99× Grande potion de soin, 99× Élixir de force",
                                   completed=True)
    for quests in ([], [long_quest] * 3):
        out = tmp_path / f"q{len(quests)}.png"
        screens.compose_quests(str(out), title="📅 Quêtes du jour", subtitle=LONG, quests=quests, empty_text="Rien.")
        _check(out)


def test_solde_du_jour(tmp_path):
    out = tmp_path / "d.png"
    screens.compose_daily(str(out), name=LONG, streak=365, gold=9_999_999, bonus_pct=90, days_missed=3,
                          streak_before=200, guard_used=True, titles=["🏛️ Pilier de la taverne"] * 2,
                          bonus_items=[("Potion", 3)])
    _check(out)


def test_defis(tmp_path):
    card = screens.TrialCard("dps", "⚔️ DPS", "Une variante au nom très long " * 2, "Description " * 40,
                             "9 999 999 · 99 essais · 1er sur 300")
    out = tmp_path / "t.png"
    screens.compose_trials(str(out), title="🎯 Défis", subtitle=LONG, cards=[card] * 3, week="x " * 200, banner="🎁 x")
    _check(out)


def test_temps_de_recharge_et_inventaire(tmp_path):
    out = tmp_path / "c.png"
    screens.compose_cooldowns(str(out), name=LONG, timers=[screens.Timer("🌅 " + "x" * 80, "prêt à 00:00 · dans 23 h 59")] * 6,
                              tickets="🎟️ " + "y" * 200, extras=["🧪 " + "z" * 200])
    _check(out)
    slots = [screens.Slot("potion_soin", "Un objet au nom très très long " * 3, 10 ** 9)] * 50
    out = tmp_path / "i.png"
    screens.compose_inventory(str(out), name=LONG, page_label="🧪 Consommables", slots=slots, empty_text="")
    _check(out)                                                             # 32 tuiles au plus, le reste compté


def test_un_rendu_rate_rend_la_main_au_texte():
    def boom(*a, **k):
        raise RuntimeError("Pillow en panne")

    assert image_embed(boom, "x", None) is None


def test_listes_classement_bourse_et_essai(tmp_path):
    rows = [screens.Row("🏹", "Un nom de titre très long " * 4, "⭐ affiché", "détail " * 60, ratio=0.4)] * 12
    out = tmp_path / "l.png"
    screens.compose_list(str(out), title="🏷️ " + LONG, subtitle=LONG, sections=[screens.Section("🔒 Chasse", rows)],
                         chips=["🏷️ 2 sur 83"], footer="x " * 200)
    _check(out)
    out = tmp_path / "lb.png"
    entries = [(LONG, "9 999 999 999 or")] * 10
    screens.compose_leaderboard(str(out), title="Or", entries=entries, viewer_rank=42, viewer=(LONG, "1 or"), total=300)
    _check(out)
    screens.compose_leaderboard(str(out), title="Or", entries=[], viewer_rank=None, viewer=None, total=0)
    _check(out)
    out = tmp_path / "g.png"
    screens.compose_gold(str(out), name=LONG, gold=10 ** 12, career=10 ** 12, is_self=False)
    _check(out)
    out = tmp_path / "a.png"
    screens.compose_attempt(str(out), role="soutien", label="💚 Soutien", variant="x" * 60, score="9 999 999",
                            unit="PV soignés", detail="y" * 200, improved=False, best="9 999 999",
                            place="300e sur 300 · essai n°999", gold="🎁 +9 999 or")
    _check(out)


def test_les_titres_tiennent_en_pages_d_image():
    from app.bot.embeds.title_embeds import ROWS_PER_PAGE, title_image_pages
    from app.infrastructure.titles.title_loader import list_definitions

    defs = list_definitions()
    pages = title_image_pages(defs[:5], defs[5:], {d.code: "**1/50** victoires" for d in defs})
    assert all(sum(len(s.rows) for s in page) <= ROWS_PER_PAGE for page in pages)
    shown = [r.text for page in pages for s in page for r in s.rows]
    assert sorted(shown) == sorted(d.name for d in defs)                  # chaque titre, une fois
    assert all("*" not in r.sub for page in pages for s in page for r in s.rows)
