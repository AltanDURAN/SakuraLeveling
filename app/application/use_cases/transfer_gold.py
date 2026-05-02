from dataclasses import dataclass

from app.infrastructure.db.repositories.player_repository import PlayerRepository


@dataclass
class TransferGoldResult:
    success: bool
    message: str
    amount: int = 0
    sender_balance_after: int = 0


class TransferGoldUseCase:
    """Transfert d'or unilatéral entre deux joueurs (commande /pay).

    Sécurité :
    - amount strictement positif (≥ 1)
    - sender ≠ receiver
    - sender doit avoir un profil (auto-créé)
    - receiver doit avoir un profil (refus si non, pas d'auto-create)
    - sender doit avoir au moins `amount` en or
    - opération atomique : decrement sender + increment receiver dans la même
      session SQLAlchemy

    Note : l'or transféré n'est PAS comptabilisé dans `gold_earned_total` du
    receiver (cohérent avec /admin give_gold et /trade : seuls les gains
    "via le jeu" comptent dans les stats de carrière).
    """

    def __init__(self, player_repository: PlayerRepository):
        self.player_repository = player_repository

    def execute(
        self,
        sender_discord_id: int,
        sender_username: str,
        sender_display_name: str,
        receiver_discord_id: int,
        receiver_display_name: str,
        amount: int,
    ) -> TransferGoldResult:
        if amount <= 0:
            return TransferGoldResult(
                success=False,
                message="❌ Le montant doit être strictement positif.",
            )

        if sender_discord_id == receiver_discord_id:
            return TransferGoldResult(
                success=False,
                message="❌ Vous ne pouvez pas vous payer à vous-même.",
            )

        sender_profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=sender_discord_id,
            username=sender_username,
            display_name=sender_display_name,
        )

        receiver_profile = self.player_repository.get_by_discord_id(receiver_discord_id)
        if receiver_profile is None:
            return TransferGoldResult(
                success=False,
                message=f"❌ {receiver_display_name} n'a pas encore de profil joueur.",
            )

        if sender_profile.resources.gold < amount:
            return TransferGoldResult(
                success=False,
                message=(
                    f"❌ Fonds insuffisants : il vous manque "
                    f"**{amount - sender_profile.resources.gold}** or "
                    f"(possédé : {sender_profile.resources.gold}, à envoyer : {amount})."
                ),
            )

        # Atomic
        self.player_repository.add_gold(sender_profile.player.id, -amount)
        self.player_repository.add_gold(receiver_profile.player.id, amount)

        return TransferGoldResult(
            success=True,
            message=(
                f"✅ **{amount}** or envoyé à {receiver_display_name}."
            ),
            amount=amount,
            sender_balance_after=sender_profile.resources.gold - amount,
        )
