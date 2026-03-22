class ProgressionService:
    def apply_level_up(
        self,
        current_level: int,
        current_xp: int,
        gained_xp: int,
        current_skill_points: int,
    ) -> tuple[int, int, int]:
        new_xp = current_xp + gained_xp
        new_level = current_level
        new_skill_points = current_skill_points

        while new_xp >= self.xp_required_for_next_level(new_level):
            required_xp = self.xp_required_for_next_level(new_level)
            new_xp -= required_xp
            new_level += 1
            new_skill_points += 1

        return new_level, new_xp, new_skill_points

    def xp_required_for_next_level(self, level: int) -> int:
        return 100 * level