from dataclasses import dataclass


@dataclass
class LeaderboardEntry:
    player_id: int
    display_name: str
    value: int
    formatted_value: str


@dataclass
class Leaderboard:
    category_code: str
    category_label: str
    entries: list[LeaderboardEntry]


class LeaderboardService:
    """Tri et formatage d'entrées de classement.

    La logique pure de ranking — récupération des données reste dans
    l'use case qui orchestre les repositories.
    """

    def rank(
        self,
        scored: list[tuple[int, str, int]],
        limit: int = 10,
        format_value=str,
    ) -> list[LeaderboardEntry]:
        sorted_entries = sorted(scored, key=lambda row: row[2], reverse=True)
        top = sorted_entries[:limit]

        return [
            LeaderboardEntry(
                player_id=row[0],
                display_name=row[1],
                value=row[2],
                formatted_value=format_value(row[2]),
            )
            for row in top
        ]
