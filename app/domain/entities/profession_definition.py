from dataclasses import dataclass
from datetime import datetime


@dataclass
class ProfessionDefinition:
    id: int
    code: str
    name: str
    description: str
    created_at: datetime
    updated_at: datetime