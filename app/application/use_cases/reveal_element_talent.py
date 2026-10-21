"""La voyante révèle le talent caché du joueur dans UN élément.

Ysaline (`/voyante`, bouton dans `/affinites`) : on choisit l'élément, on paie,
le talent est révélé dans la foulée. Le prix monte à chaque lecture
(`reading_prices`, section `voyante` d'artisans.json) — puits d'or ; la
première est offerte. 8 éléments ⇒ 8 lectures au plus, propres à chaque joueur.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.services.element_talent_service import ElementTalent, paper_price
from app.infrastructure.db.repositories.element_affinity_repository import (
    ElementAffinityRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.shared.enums import ALL_ELEMENTS


@dataclass(frozen=True)
class PaperStatus:
    """Ce qu'il faut pour afficher l'offre : prix de la prochaine lecture et
    éléments encore inconnus."""
    next_price: int | None          # None = tous les talents sont connus
    unrevealed: tuple[str, ...]
    revealed: dict[str, ElementTalent]
    gold: int


@dataclass(frozen=True)
class RevealResult:
    success: bool
    message: str
    element: str = ""
    talent: ElementTalent | None = None
    price: int = 0


class RevealElementTalentUseCase:
    def __init__(self, session, prices: tuple[int, ...] | list[int]) -> None:
        self.session = session
        self.prices = list(prices)
        self.players = PlayerRepository(session)
        self.affinities = ElementAffinityRepository(session)

    def status(self, player_id: int) -> PaperStatus:
        talents = self.affinities.get_talents(player_id)
        revealed_codes = self.affinities.revealed_elements(player_id)
        profile = self.players.get_profile_by_player_id(player_id)
        codes = [e.value for e in ALL_ELEMENTS]
        return PaperStatus(
            next_price=paper_price(len(revealed_codes), self.prices),
            unrevealed=tuple(c for c in codes if c not in revealed_codes),
            revealed={c: talents[c] for c in codes if c in revealed_codes and c in talents},
            gold=profile.resources.gold if profile else 0,
        )

    def execute(self, player_id: int, element: str) -> RevealResult:
        if element not in {e.value for e in ALL_ELEMENTS}:
            return RevealResult(False, "Élément inconnu.")
        status = self.status(player_id)
        if status.next_price is None:
            return RevealResult(False, "Tu connais déjà tous tes talents élémentaires.")
        if element not in status.unrevealed:
            return RevealResult(False, "Tu connais déjà ton talent dans cet élément.")
        price = status.next_price
        if status.gold < price:
            return RevealResult(
                False, f"Il te manque {price - status.gold} or pour cette lecture.", element,
                price=price,
            )
        talent = self.affinities.reveal(player_id, element)  # flush
        if price:
            self.players.add_gold(player_id, -price)  # commit (révélation comprise)
        else:
            self.session.commit()
        return RevealResult(True, "", element, talent, price)
