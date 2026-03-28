class ProfessionService:
    def apply_xp(self, level: int, xp: int, gained_xp: int) -> tuple[int, int]:
        xp += gained_xp

        while xp >= level * 50:
            xp -= level * 50
            level += 1

        return level, xp