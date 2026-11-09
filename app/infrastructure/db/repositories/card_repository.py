"""Cartes à collectionner : ce que possède un joueur et son état (pétales,
pitié, booster offert). Les cartes sont des objets d'inventaire de la
catégorie `carte` (cf. `card_loader`)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.cards.card_loader import parse_item_code
from app.infrastructure.db.models.card_model import PlayerCardStateModel
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel
from app.infrastructure.db.models.item_model import ItemDefinitionModel
from app.shared.enums import ItemCategory


class CardRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def state(self, player_id: int) -> PlayerCardStateModel:
        """La ligne du joueur (créée au besoin, sans valider)."""
        row = self.session.get(PlayerCardStateModel, player_id)
        if row is None:
            row = PlayerCardStateModel(player_id=player_id, updated_at=datetime.now(UTC))
            self.session.add(row)
            self.session.flush()
        return row

    def find_state(self, player_id: int) -> PlayerCardStateModel | None:
        return self.session.get(PlayerCardStateModel, player_id)

    def owned(self, player_id: int) -> tuple[dict[str, int], dict[str, int]]:
        """(normales, brillantes) : code de carte → exemplaires."""
        rows = self.session.execute(
            select(ItemDefinitionModel.code, PlayerInventoryItemModel.quantity)
            .join(ItemDefinitionModel, ItemDefinitionModel.id == PlayerInventoryItemModel.item_definition_id)
            .where(PlayerInventoryItemModel.player_id == player_id,
                   ItemDefinitionModel.category == ItemCategory.CARD.value,
                   PlayerInventoryItemModel.quantity > 0)
        ).all()
        normal: dict[str, int] = {}
        brillante: dict[str, int] = {}
        for code, quantity in rows:
            parsed = parse_item_code(code)
            if parsed is None:
                continue
            card, shiny = parsed
            target = brillante if shiny else normal
            target[card] = target.get(card, 0) + int(quantity)
        return normal, brillante

    def item_ids(self) -> dict[str, int]:
        """Code d'objet → identifiant, pour toutes les cartes en base."""
        rows = self.session.execute(
            select(ItemDefinitionModel.code, ItemDefinitionModel.id)
            .where(ItemDefinitionModel.category == ItemCategory.CARD.value)
        ).all()
        return {code: item_id for code, item_id in rows}

    def album_sizes(self) -> dict[int, int]:
        """Joueur → cartes DIFFÉRENTES possédées (normale ou brillante)."""
        rows = self.session.execute(
            select(PlayerInventoryItemModel.player_id, ItemDefinitionModel.code)
            .join(ItemDefinitionModel, ItemDefinitionModel.id == PlayerInventoryItemModel.item_definition_id)
            .where(ItemDefinitionModel.category == ItemCategory.CARD.value,
                   PlayerInventoryItemModel.quantity > 0)
        ).all()
        cards: dict[int, set[str]] = {}
        for player_id, code in rows:
            parsed = parse_item_code(code)
            if parsed is not None:
                cards.setdefault(player_id, set()).add(parsed[0])
        return {player_id: len(codes) for player_id, codes in cards.items()}

    def states(self) -> dict[int, PlayerCardStateModel]:
        return {row.player_id: row for row in self.session.execute(select(PlayerCardStateModel)).scalars()}
