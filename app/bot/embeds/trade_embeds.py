"""Embeds pour /trade : récapitulatif d'une proposition d'échange."""

from datetime import UTC, datetime

import discord

from app.bot.embeds.limits import add_lines, clip

from app.domain.entities.trade import Trade, TradeSide, TradeStatus
from app.domain.services.gear_service import gear_label
from app.shared.enums import GOLD_EMOJI
from app.shared.formatters import discord_countdown, format_int


_STATUS_LABELS = {
    TradeStatus.PENDING: ("⌛ En attente", discord.Color.blurple()),
    TradeStatus.ACCEPTED: ("✅ Échange réalisé", discord.Color.green()),
    TradeStatus.REFUSED: ("✋ Refusé", discord.Color.red()),
    TradeStatus.CANCELLED: ("🛑 Annulé", discord.Color.dark_grey()),
    TradeStatus.EXPIRED: ("⏰ Expiré", discord.Color.dark_grey()),
    TradeStatus.FAILED: ("⚠️ Échec (ressources manquantes)", discord.Color.orange()),
}


def _format_offer(items, gold: int) -> list[str]:
    parts: list[str] = []
    if gold > 0:
        parts.append(f"{GOLD_EMOJI} **{format_int(gold)}** or")
    for offer in items:
        if offer.gear_id is not None:
            parts.append(f"**{gear_label(offer.item_name, offer.rarity or 'common')}**")
        else:
            parts.append(f"{offer.quantity}× **{offer.item_name}**")
    return parts


def build_trade_embed(trade: Trade) -> discord.Embed:
    label, color = _STATUS_LABELS.get(
        trade.status, ("Inconnu", discord.Color.default())
    )

    embed = discord.Embed(
        title=f"🤝 Échange n° {trade.id} — {label}",
        color=color,
    )

    # Côté initiateur
    # Plusieurs champs au besoin (un seul dépassait les 1 024 caractères à
    # partir de 25 lots) : tout ce qui s'échange doit rester visible.
    add_lines(embed, clip(f"📤 {trade.initiator_display_name} propose", 250),
              _format_offer(trade.items_offered_by(TradeSide.INITIATOR), trade.initiator_gold_offered),
              inline=True, max_fields=3, empty="_Rien_")

    # Côté destinataire
    add_lines(embed, clip(f"📥 {trade.target_display_name} doit donner", 250),
              _format_offer(trade.items_offered_by(TradeSide.TARGET), trade.target_gold_offered),
              inline=True, max_fields=3, empty="_Rien_")

    # Discord n'affiche pas les <t:…> d'un pied de page (on y lisait
    # « Expire <t:1793747027:R> ») : l'échéance va dans la description, la
    # date de mise à jour dans l'horodatage de l'embed.
    if trade.status == TradeStatus.PENDING and trade.expires_at is not None:
        embed.description = f"⏳ Expire {discord_countdown(_utc(trade.expires_at))}."
    elif trade.updated_at is not None:
        embed.set_footer(text="Mis à jour")
        embed.timestamp = _utc(trade.updated_at)

    return embed


def _utc(moment: datetime) -> datetime:
    """La base rend des dates SANS fuseau, en UTC : sans ce rappel, Python
    les lirait à l'heure du serveur (une heure d'écart à Paris)."""
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment
