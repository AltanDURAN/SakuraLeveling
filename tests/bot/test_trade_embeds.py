"""Récapitulatif d'un échange : l'échéance doit être LISIBLE (07/11/2026 :
Discord n'affiche pas les <t:…> d'un pied de page, on y lisait le code brut)."""

from datetime import UTC, datetime, timedelta

from app.bot.embeds.trade_embeds import build_trade_embed
from app.domain.entities.trade import Trade, TradeStatus


def _trade(status, **dates):
    return Trade(id=3, initiator_player_id=1, initiator_discord_id=11, initiator_display_name="Alice",
                 target_player_id=2, target_discord_id=22, target_display_name="Bob", status=status,
                 initiator_gold_offered=500, target_gold_offered=0, **dates)


def test_un_echange_en_attente_dit_quand_il_expire_et_a_quelle_heure():
    expires = datetime.now(UTC).replace(tzinfo=None, microsecond=0) + timedelta(minutes=5)   # naïve, comme la base
    embed = build_trade_embed(_trade(TradeStatus.PENDING, expires_at=expires))
    ts = int(expires.replace(tzinfo=UTC).timestamp())
    assert embed.description == f"⏳ Expire <t:{ts}:R> (à <t:{ts}:t>)."
    assert embed.footer.text is None


def test_un_echange_termine_est_horodate_sans_code_brut():
    updated = datetime(2026, 11, 7, 16, 41)                                  # naïve : UTC
    embed = build_trade_embed(_trade(TradeStatus.ACCEPTED, updated_at=updated))
    assert embed.footer.text == "Mis à jour"
    assert embed.timestamp == updated.replace(tzinfo=UTC)
    assert "<t:" not in (embed.description or "")
