"""Fiches des défis (`/defi`) : la petite récompense du premier défi de la
journée (09/11/2026, demande de l'auteur)."""

from datetime import date

from app.application.use_cases.role_trials import AttemptOutcome
from app.bot.embeds.role_trial_embeds import build_attempt_embed, build_day_embed
from app.domain.services import role_trial_service as rts
from app.shared.enums import GOLD_EMOJI

DAY = date(2026, 11, 9)


def _outcome(gold: int) -> AttemptOutcome:
    return AttemptOutcome("dps", rts.variant_of_day(DAY, "dps"), 1200, 1200, True, 1, 1, 3, 40, True, gold)


def test_le_resultat_annonce_l_or_du_premier_defi():
    assert f"**+250** {GOLD_EMOJI}" in build_attempt_embed(_outcome(250)).description
    assert GOLD_EMOJI not in build_attempt_embed(_outcome(0)).description


def test_le_programme_dit_si_la_recompense_du_jour_reste_a_prendre():
    public = build_day_embed(DAY).description                     # annonce de minuit
    assert f"{rts.FIRST_OF_DAY_GOLD_PER_LEVEL} × ton niveau" in public
    assert f"**250** {GOLD_EMOJI}" in build_day_embed(DAY, {}, {}, 250).description
    done = build_day_embed(DAY, {"dps": (1200, 1, 1, 3)}, {}, 250).description
    assert "prise" in done and GOLD_EMOJI not in done
