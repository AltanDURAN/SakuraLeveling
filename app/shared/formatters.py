"""Helpers de formatage partagés entre les embeds Discord."""


def format_int(value: int) -> str:
    """Formate un entier avec espaces comme séparateurs de milliers (style FR).

    Exemples : 1500 → "1 500", 1234567 → "1 234 567".
    """
    return f"{value:,}".replace(",", " ")


_MONTHS_FR = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
              "septembre", "octobre", "novembre", "décembre")


def discord_countdown(moment) -> str:
    """« dans 2 minutes (à 21:05) » : le compte à rebours ET l'heure. Discord
    les affiche à l'heure et dans la langue de chaque joueur (« 21:05 » en
    français) ; une heure écrite en dur serait fausse hors de France."""
    ts = int(moment.timestamp())
    return f"<t:{ts}:R> (à <t:{ts}:t>)"


def format_date_fr(day) -> str:
    """Une date en toutes lettres : 7 novembre 2026 (1er pour le premier du mois)."""
    first = "1er" if day.day == 1 else str(day.day)
    return f"{first} {_MONTHS_FR[day.month - 1]} {day.year}"
