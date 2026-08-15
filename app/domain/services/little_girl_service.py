from __future__ import annotations

import random
from dataclasses import dataclass

# Choix possibles d'un participant.
CHOICE_HELP = "aider"
CHOICE_IGNORE = "ignorer"

TITLE_CODE = "ma_survie_avant_tout"


@dataclass(frozen=True)
class LittleGirlConfig:
    trap_probability: int = 50          # % que ce soit un piège
    gold_loss_per_level: int = 10       # or perdu = coef × niveau
    buff_multiplier: float = 1.1
    buff_duration_hours: int = 3
    debuff_multiplier: float = 0.5
    debuff_duration_hours: int = 3
    title_chance: int = 10              # % d'obtenir le titre (ignorer + piège)


@dataclass(frozen=True)
class LittleGirlConsequence:
    """Ce qu'il faut appliquer à UN participant + un texte de récap."""

    summary: str
    buff_multiplier: float = 0.0        # > 0 → appliquer un buff temporaire
    buff_hours: int = 0
    debuff_multiplier: float = 0.0      # > 0 → appliquer un debuff temporaire
    debuff_hours: int = 0
    gold_loss: int = 0                  # or à retirer
    halve_hp: bool = False              # diviser les PV COURANTS par 2
    grant_title: str = ""              # code de titre à octroyer


class LittleGirlService:
    """Résout l'issue d'un participant de l'événement « petite fille ».

    L'issue globale (piège vs vraie petite fille) est tirée UNE fois pour tout
    l'événement (`roll_is_trap`). Chaque participant a ensuite sa conséquence
    selon son choix. Le tirage du titre (ignorer + piège) est individuel.
    """

    def roll_is_trap(self, config: LittleGirlConfig, rng: random.Random | None = None) -> bool:
        rng = rng or random
        return rng.uniform(0, 100) < max(0, min(100, config.trap_probability))

    def resolve(
        self,
        choice: str,
        is_trap: bool,
        player_level: int,
        config: LittleGirlConfig,
        has_title: bool,
        rng: random.Random | None = None,
    ) -> LittleGirlConsequence:
        rng = rng or random
        choice = (choice or "").strip().lower()

        if choice == CHOICE_HELP:
            if not is_trap:
                # Vraie petite fille aidée → buff.
                return LittleGirlConsequence(
                    summary=(
                        "Tu as aidé une vraie petite fille perdue. Par gratitude, "
                        f"tu reçois une bénédiction : **+{round((config.buff_multiplier - 1) * 100)}% "
                        f"à toutes tes stats pendant {config.buff_duration_hours}h**. 😇"
                    ),
                    buff_multiplier=config.buff_multiplier,
                    buff_hours=config.buff_duration_hours,
                )
            # Piège : c'était un monstre déguisé.
            gold_loss = max(0, config.gold_loss_per_level * max(1, player_level))
            return LittleGirlConsequence(
                summary=(
                    "C'était un **piège** ! La « petite fille » était un monstre "
                    f"déguisé. Il te dépouille de **{gold_loss} or** et te laisse à "
                    "**moitié PV**. 😈"
                ),
                gold_loss=gold_loss,
                halve_hp=True,
            )

        if choice == CHOICE_IGNORE:
            if not is_trap:
                # Vraie petite fille ignorée → réputation entamée + debuff.
                return LittleGirlConsequence(
                    summary=(
                        "Tu as ignoré une vraie petite fille en détresse… Ta "
                        "réputation en prend un coup et le malaise te ronge : "
                        f"**toutes tes stats positives sont divisées par "
                        f"{round(1 / config.debuff_multiplier) if config.debuff_multiplier else 2} "
                        f"pendant {config.debuff_duration_hours}h**. 💔"
                    ),
                    debuff_multiplier=config.debuff_multiplier,
                    debuff_hours=config.debuff_duration_hours,
                )
            # Piège ignoré → instinct de survie récompensé (1 chance sur N).
            win = rng.uniform(0, 100) < max(0, min(100, config.title_chance))
            if not win:
                return LittleGirlConsequence(
                    summary=(
                        "C'était un piège, et tu l'as évité en l'ignorant. Ton "
                        "instinct t'a sauvé… mais tu repars sans rien cette fois. 🚶"
                    )
                )
            if has_title:
                # Déjà détenteur : le titre ne s'obtient qu'une fois → buff à la place.
                return LittleGirlConsequence(
                    summary=(
                        "C'était un piège, évité de justesse ! Tu détiens déjà le "
                        "titre **Ma survie avant tout** — tu reçois à la place "
                        f"**+{round((config.buff_multiplier - 1) * 100)}% à toutes "
                        f"tes stats pendant {config.buff_duration_hours}h**. 🛡️"
                    ),
                    buff_multiplier=config.buff_multiplier,
                    buff_hours=config.buff_duration_hours,
                )
            return LittleGirlConsequence(
                summary=(
                    "C'était un piège, évité de justesse ! Ton instinct de survie "
                    "te vaut le titre légendaire **« Ma survie avant tout »** ! 🛡️✨"
                ),
                grant_title=TITLE_CODE,
            )

        # Choix inconnu / pas de participation → rien.
        return LittleGirlConsequence(summary="")
