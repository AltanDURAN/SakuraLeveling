from datetime import datetime, UTC

from sqlalchemy import Column, Integer, String, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


from datetime import datetime

from sqlalchemy import Integer, String, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class MobDefinitionModel(Base):
    __tablename__ = "mob_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(255), default="")
    image_name: Mapped[str] = mapped_column(String(100), nullable=True)

    max_hp: Mapped[int] = mapped_column(Integer)
    current_hp: Mapped[int] = mapped_column(Integer)
    attack: Mapped[int] = mapped_column(Integer)
    defense: Mapped[int] = mapped_column(Integer)
    speed: Mapped[int] = mapped_column(Integer)
    crit_chance = Column(Integer, nullable=False, default=0)
    crit_damage = Column(Integer, nullable=False, default=100)
    dodge = Column(Integer, nullable=False, default=0)
    hp_regeneration = Column(Integer, nullable=False, default=0)

    xp_reward: Mapped[int] = mapped_column(Integer, default=0)
    gold_reward: Mapped[int] = mapped_column(Integer, default=0)
    spawn_weight: Mapped[int] = mapped_column(Integer, default=1)
    loot_table_json: Mapped[list | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now(UTC))