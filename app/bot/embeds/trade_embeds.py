"""Embeds pour /trade : récapitulatif d'une proposition d'échange."""

from datetime import datetime, UTC

import discord

from app.domain.entities.trade import Trade, TradeSide, TradeStatus
from app.shared.formatters import format_int


_STATUS_LABELS = {
    TradeStatus.PENDING: ("⌛ En attente", discord.Color.blurple()),
    TradeStatus.ACCEPTED: ("✅ Échange réalisé", discord.Color.green()),
    TradeStatus.REFUSED: ("✋ Refusé", discord.Color.red()),
    TradeStatus.CANCELLED: ("🛑 Annulé", discord.Color.dark_grey()),
    TradeStatus.EXPIRED: ("⏰ Expiré", discord.Color.dark_grey()),
    TradeStatus.FAILED: ("⚠️ Échec (ressources manquantes)", discord.Color.orange()),
}


def _format_offer(items, gold: int) -> str:
    parts: list[str] = []
    if gold > 0:
        parts.append(f"💰 **{format_int(gold)}** or")
    for offer in items:
        parts.append(f"{offer.quantity}× **{offer.item_name}**")
    return "\n".join(parts) if parts else "_Rien_"


def build_trade_embed(trade: Trade) -> discord.Embed:
    label, color = _STATUS_LABELS.get(
        trade.status, ("Inconnu", discord.Color.default())
    )

    embed = discord.Embed(
        title=f"🤝 Trade #{trade.id} — {label}",
        color=color,
    )

    # Côté initiateur
    initiator_offer_text = _format_offer(
        trade.items_offered_by(TradeSide.INITIATOR),
        trade.initiator_gold_offered,
    )
    embed.add_field(
        name=f"📤 {trade.initiator_display_name} propose",
        value=initiator_offer_text,
        inline=True,
    )

    # Côté destinataire
    target_offer_text = _format_offer(
        trade.items_offered_by(TradeSide.TARGET),
        trade.target_gold_offered,
    )
    embed.add_field(
        name=f"📥 {trade.target_display_name} doit donner",
        value=target_offer_text,
        inline=True,
    )

    if trade.status == TradeStatus.PENDING and trade.expires_at is not None:
        expires_at = trade.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        ts = int(expires_at.timestamp())
        embed.set_footer(text=f"Expire <t:{ts}:R>")
    else:
        ts = int(trade.updated_at.timestamp()) if trade.updated_at else 0
        embed.set_footer(text=f"Mis à jour <t:{ts}:R>")

    return embed
