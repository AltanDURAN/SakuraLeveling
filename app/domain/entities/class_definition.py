from dataclasses import dataclass
from datetime import datetime


@dataclass
class ClassDefinition:
    id: int
    code: str
    name: str
    description: str
    stat_bonuses: dict | None
    created_at: datetime
    updated_at: datetime