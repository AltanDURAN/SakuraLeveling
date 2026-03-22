from dataclasses import dataclass


@dataclass
class Reward:
    xp: int
    gold: int
    items: list[tuple[str, int]]