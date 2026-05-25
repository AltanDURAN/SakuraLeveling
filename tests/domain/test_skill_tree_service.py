from app.domain.entities.skill_node import SkillEffect, SkillNode, SkillPosition
from app.domain.entities.skill_tree_definition import SkillTreeDefinition
from app.domain.services.skill_tree_service import SkillTreeService


def _make_node(
    code: str,
    name: str = "",
    max_level: int = 5,
    costs: list[int] | None = None,
    effects: list[SkillEffect] | None = None,
    prerequisites: list[str] | None = None,
) -> SkillNode:
    return SkillNode(
        code=code,
        name=name or code,
        description="",
        icon="",
        max_level=max_level,
        costs=costs or [1] * max_level,
        effects=effects or [],
        prerequisites=prerequisites or [],
        position=SkillPosition(x=0, y=0),
    )


def _build_simple_tree() -> SkillTreeDefinition:
    """Arbre minimal : root → atk → atk2 et root → def."""
    nodes = {
        "root": _make_node("root", max_level=1, costs=[0]),
        "atk": _make_node(
            "atk",
            max_level=3,
            costs=[1, 2, 3],
            effects=[SkillEffect(type="atk_percent", values=[2, 3, 5])],
            prerequisites=["root"],
        ),
        "atk2": _make_node(
            "atk2",
            max_level=2,
            costs=[2, 4],
            effects=[SkillEffect(type="crit_chance_flat", values=[1, 2])],
            prerequisites=["atk"],
        ),
        "def": _make_node(
            "def",
            max_level=2,
            costs=[1, 2],
            effects=[SkillEffect(type="def_percent", values=[3, 5])],
            prerequisites=["root"],
        ),
    }
    return SkillTreeDefinition(root="root", skills=nodes)


# ---------- aggregate_bonuses ----------


def test_aggregate_bonuses_sums_cumulative_values_per_level():
    defn = _build_simple_tree()
    svc = SkillTreeService(defn)

    # atk lvl 2 → cumul des paliers 1+2 = 3 → atk_percent = 0.03
    bonuses = svc.aggregate_bonuses({"root": 1, "atk": 2})

    assert abs(bonuses.atk_percent - 0.03) < 1e-9
    assert bonuses.def_percent == 0.0
    assert bonuses.crit_chance_flat == 0


def test_aggregate_bonuses_combines_multiple_skills():
    defn = _build_simple_tree()
    svc = SkillTreeService(defn)

    # values cumulatives : atk lvl 3 → values[2]=5 → 0.05
    #                     def lvl 2 → values[1]=5 → 0.05
    #                     atk2 lvl 1 → values[0]=1 → +1 crit_chance
    bonuses = svc.aggregate_bonuses(
        {"root": 1, "atk": 3, "atk2": 1, "def": 2}
    )

    assert abs(bonuses.atk_percent - 0.05) < 1e-9
    assert abs(bonuses.def_percent - 0.05) < 1e-9
    assert bonuses.crit_chance_flat == 1


def test_aggregate_bonuses_empty_allocations_returns_neutral():
    defn = _build_simple_tree()
    svc = SkillTreeService(defn)

    bonuses = svc.aggregate_bonuses({})

    assert bonuses.atk_percent == 0.0
    assert bonuses.drop_rate_multiplier == 1.0


def test_aggregate_bonuses_flat_nodes_accumulate_uncapped():
    """Les nœuds plats (moteur infini) ne sont jamais plafonnés."""
    nodes = {
        "root": _make_node("root", max_level=1, costs=[0]),
        "atk_flat": _make_node(
            "atk_flat", max_level=3, costs=[1, 1, 1],
            effects=[SkillEffect(type="atk_flat", values=[5, 10, 15])],
            prerequisites=["root"],
        ),
    }
    defn = SkillTreeDefinition(root="root", skills=nodes)
    svc = SkillTreeService(defn)

    bonuses = svc.aggregate_bonuses({"root": 1, "atk_flat": 3})
    assert bonuses.atk_flat == 15  # cumulatif lvl 3
    assert bonuses.atk_percent == 0.0


def test_aggregate_bonuses_caps_percent_at_200():
    """Le % de stat est plafonné à +200% (×3), peu importe le cumul."""
    nodes = {
        "root": _make_node("root", max_level=1, costs=[0]),
        # un nœud qui donnerait +500% sans le cap
        "atk_pct": _make_node(
            "atk_pct", max_level=1, costs=[1],
            effects=[SkillEffect(type="atk_percent", values=[500])],
            prerequisites=["root"],
        ),
    }
    defn = SkillTreeDefinition(root="root", skills=nodes)
    svc = SkillTreeService(defn)

    bonuses = svc.aggregate_bonuses({"root": 1, "atk_pct": 1})
    assert bonuses.atk_percent == 2.0  # capé à +200%


def test_aggregate_bonuses_caps_economy_at_100():
    nodes = {
        "root": _make_node("root", max_level=1, costs=[0]),
        "gold": _make_node(
            "gold", max_level=1, costs=[1],
            effects=[SkillEffect(type="gold_drop_percent", values=[300])],
            prerequisites=["root"],
        ),
    }
    defn = SkillTreeDefinition(root="root", skills=nodes)
    svc = SkillTreeService(defn)

    bonuses = svc.aggregate_bonuses({"root": 1, "gold": 1})
    assert bonuses.gold_drop_percent == 1.0  # capé à +100%


def test_aggregate_bonuses_ignores_unknown_skill_code():
    defn = _build_simple_tree()
    svc = SkillTreeService(defn)

    # "ghost" n'existe pas dans la définition → ignoré silencieusement
    bonuses = svc.aggregate_bonuses({"root": 1, "ghost": 5})

    assert bonuses.atk_percent == 0.0


def test_aggregate_bonuses_drop_rate_multiplier_starts_at_one():
    defn = SkillTreeDefinition(
        root="root",
        skills={
            "root": _make_node("root", max_level=1, costs=[0]),
            "luck": _make_node(
                "luck",
                max_level=2,
                costs=[1, 2],
                effects=[SkillEffect(type="drop_rate_multiplier", values=[5, 5])],
                prerequisites=["root"],
            ),
        },
    )
    svc = SkillTreeService(defn)

    # values cumulatives [5, 5] : lvl 2 → 5 → drop_rate_multiplier = 1 + 0.05 = 1.05
    bonuses = svc.aggregate_bonuses({"root": 1, "luck": 2})

    assert abs(bonuses.drop_rate_multiplier - 1.05) < 1e-9


# ---------- compute_node_state ----------


def test_node_state_locked_when_prerequisites_missing():
    defn = _build_simple_tree()
    svc = SkillTreeService(defn)

    # Sans root, atk est verrouillé
    assert svc.compute_node_state({}, "atk") == "locked"


def test_node_state_unlockable_when_prerequisites_satisfied_and_level_zero():
    defn = _build_simple_tree()
    svc = SkillTreeService(defn)

    assert svc.compute_node_state({"root": 1}, "atk") == "unlockable"


def test_node_state_in_progress_when_level_between_one_and_max():
    defn = _build_simple_tree()
    svc = SkillTreeService(defn)

    assert svc.compute_node_state({"root": 1, "atk": 2}, "atk") == "in_progress"


def test_node_state_maxed_when_at_max_level():
    defn = _build_simple_tree()
    svc = SkillTreeService(defn)

    assert svc.compute_node_state({"root": 1, "atk": 3}, "atk") == "maxed"


# ---------- compute_unlockable_skills ----------


def test_unlockable_skills_excludes_locked_and_maxed():
    defn = _build_simple_tree()
    svc = SkillTreeService(defn)

    # root pris, atk au max, def lvl 1 → seules atk2 et def restent débloquables
    candidates = svc.compute_unlockable_skills(
        {"root": 1, "atk": 3, "def": 1}
    )
    codes = [n.code for n in candidates]

    assert "atk2" in codes  # prereq atk satisfait, niveau 0
    assert "def" in codes  # peut encore monter
    assert "atk" not in codes  # maxed
    assert "root" not in codes  # maxed (max_level=1)


def test_unlockable_skills_respects_limit():
    defn = _build_simple_tree()
    svc = SkillTreeService(defn)

    candidates = svc.compute_unlockable_skills({"root": 1}, limit=1)

    assert len(candidates) == 1


def test_unlockable_skills_default_limit_matches_discord_select_max():
    """Régression : la limite par défaut doit être assez haute pour ne pas
    cacher un nœud que le rendu SVG montre comme débloquable. Discord plafonne
    les Select Menus à 25 options. Ne pas baisser cette valeur sans paginer
    le menu côté bot."""
    defn = _build_simple_tree()
    svc = SkillTreeService(defn)

    # On ne passe PAS de limit explicite : doit utiliser le défaut.
    candidates = svc.compute_unlockable_skills({"root": 1, "atk": 1, "def": 1})

    # Tous les nœuds débloquables doivent être présents (pas de troncature
    # silencieuse). Dans un vrai arbre de 20+ nœuds, ce serait critique.
    state_unlockable = [
        n.code for n in defn
        if svc.compute_node_state(
            {"root": 1, "atk": 1, "def": 1}, n.code
        ) in ("unlockable", "in_progress")
    ]
    candidate_codes = [n.code for n in candidates]
    for code in state_unlockable:
        assert code in candidate_codes, (
            f"`{code}` est marqué débloquable par compute_node_state "
            f"mais absent de compute_unlockable_skills"
        )


# ---------- validate_investment ----------


def test_validate_rejects_unknown_skill():
    defn = _build_simple_tree()
    svc = SkillTreeService(defn)

    ok, msg, cost = svc.validate_investment({}, 100, "ghost")

    assert ok is False
    assert "inconnue" in msg.lower()


def test_validate_rejects_when_prerequisites_missing():
    defn = _build_simple_tree()
    svc = SkillTreeService(defn)

    ok, msg, cost = svc.validate_investment({}, 100, "atk")

    assert ok is False
    # Le parent (root) n'est pas maxé → message de verrouillage.
    assert "verrouillé" in msg.lower() or "max" in msg.lower()


def test_validate_rejects_when_at_max_level():
    defn = _build_simple_tree()
    svc = SkillTreeService(defn)

    ok, msg, cost = svc.validate_investment(
        {"root": 1, "atk": 3}, 100, "atk"
    )

    assert ok is False
    assert "max" in msg.lower()


def test_validate_rejects_when_insufficient_points():
    defn = _build_simple_tree()
    svc = SkillTreeService(defn)

    # atk lvl 1 → next coût 2, mais on n'a que 1 point
    ok, msg, cost = svc.validate_investment(
        {"root": 1, "atk": 1}, 1, "atk"
    )

    assert ok is False
    assert cost == 2
    assert "point" in msg.lower()


def test_validate_accepts_when_all_conditions_met():
    defn = _build_simple_tree()
    svc = SkillTreeService(defn)

    ok, msg, cost = svc.validate_investment({"root": 1}, 5, "atk")

    assert ok is True
    assert cost == 1  # premier palier de atk


# ---------- compute_total_refund ----------


def test_total_refund_sums_cumulative_costs():
    defn = _build_simple_tree()
    svc = SkillTreeService(defn)

    # atk lvl 3 = 1+2+3 = 6, def lvl 2 = 1+2 = 3, root lvl 1 = 0 → total 9
    refund = svc.compute_total_refund({"root": 1, "atk": 3, "def": 2})

    assert refund == 9


def test_total_refund_empty_allocations_is_zero():
    defn = _build_simple_tree()
    svc = SkillTreeService(defn)

    assert svc.compute_total_refund({}) == 0


# ---------- Prérequis : parent COMPLÈTEMENT maxé (V2) ----------


def test_node_locked_when_parent_not_fully_maxed():
    """atk (max 3) à lvl 1 ne suffit PAS à débloquer atk2 : il faut atk maxé."""
    defn = _build_simple_tree()
    svc = SkillTreeService(defn)

    # atk au niveau 1 (pas maxé) → atk2 reste verrouillé
    assert svc.compute_node_state({"root": 1, "atk": 1}, "atk2") == "locked"
    assert svc.compute_node_state({"root": 1, "atk": 2}, "atk2") == "locked"
    # atk maxé (3/3) → atk2 débloquable
    assert svc.compute_node_state({"root": 1, "atk": 3}, "atk2") == "unlockable"


def test_validate_refuses_when_parent_not_maxed():
    defn = _build_simple_tree()
    svc = SkillTreeService(defn)

    ok, msg, _ = svc.validate_investment({"root": 1, "atk": 2}, 99, "atk2")
    assert ok is False
    assert "MAX" in msg.upper()

    ok2, _, _ = svc.validate_investment({"root": 1, "atk": 3}, 99, "atk2")
    assert ok2 is True


def test_unlockable_skills_requires_maxed_parents():
    defn = _build_simple_tree()
    svc = SkillTreeService(defn)

    # root maxé (1/1) → atk et def débloquables ; atk2 non (atk pas maxé)
    codes = [n.code for n in svc.compute_unlockable_skills({"root": 1})]
    assert "atk" in codes and "def" in codes
    assert "atk2" not in codes
