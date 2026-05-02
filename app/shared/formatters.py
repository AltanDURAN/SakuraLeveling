"""Helpers de formatage partagés entre les embeds Discord."""


def format_int(value: int) -> str:
    """Formate un entier avec espaces comme séparateurs de milliers (style FR).

    Exemples : 1500 → "1 500", 1234567 → "1 234 567".
    """
    return f"{value:,}".replace(",", " ")
