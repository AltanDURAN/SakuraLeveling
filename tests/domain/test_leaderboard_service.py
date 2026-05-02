from app.domain.services.leaderboard_service import LeaderboardEntry, LeaderboardService


def test_rank_sorts_descending_by_value():
    service = LeaderboardService()

    entries = service.rank(
        scored=[(1, "Alpha", 100), (2, "Beta", 300), (3, "Gamma", 200)],
        limit=10,
    )

    assert [entry.display_name for entry in entries] == ["Beta", "Gamma", "Alpha"]
    assert [entry.value for entry in entries] == [300, 200, 100]


def test_rank_respects_limit():
    service = LeaderboardService()

    entries = service.rank(
        scored=[(i, f"P{i}", i * 10) for i in range(20)],
        limit=5,
    )

    assert len(entries) == 5
    assert entries[0].value == 190
    assert entries[-1].value == 150


def test_rank_applies_format_value():
    service = LeaderboardService()

    entries = service.rank(
        scored=[(1, "Alpha", 1500), (2, "Beta", 250)],
        limit=10,
        format_value=lambda v: f"{v} pts",
    )

    assert entries[0].formatted_value == "1500 pts"
    assert entries[1].formatted_value == "250 pts"


def test_rank_empty_input_returns_empty_list():
    service = LeaderboardService()

    entries = service.rank(scored=[], limit=10)

    assert entries == []


def test_rank_default_format_is_str():
    service = LeaderboardService()

    entries = service.rank(scored=[(1, "Alpha", 42)], limit=10)

    assert isinstance(entries[0], LeaderboardEntry)
    assert entries[0].formatted_value == "42"


def test_rank_handles_ties_stably():
    service = LeaderboardService()

    entries = service.rank(
        scored=[(1, "Alpha", 100), (2, "Beta", 100), (3, "Gamma", 100)],
        limit=10,
    )

    assert len(entries) == 3
    assert all(entry.value == 100 for entry in entries)
