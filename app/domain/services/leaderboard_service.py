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
    #: Place de celui qui regarde, s'il est classé (1 = premier).
    viewer_rank: int | None = None
    viewer_entry: LeaderboardEntry | None = None
    #: Nombre de joueurs classés.
    total: int = 0

    def focused_on(self, player_id: int | None, limit: int) -> "Leaderboard":
        """Le haut du classement, et la place de `player_id` dans l'ensemble."""
        rank = next((i for i, e in enumerate(self.entries, start=1) if e.player_id == player_id), None)
        return Leaderboard(self.category_code, self.category_label, self.entries[:limit],
                           viewer_rank=rank, viewer_entry=self.entries[rank - 1] if rank else None,
                           total=len(self.entries))


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
