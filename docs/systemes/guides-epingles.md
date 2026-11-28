# Guides épinglés (world boss, tour solo) — 07/11/2026

_Fiche sortie de CLAUDE.md le 28/11/2026 (audit) : texte inchangé, liens recalés._

Demande de l'auteur : le premier message des salons du world boss (`settings.boss_channel_id`) et de la tour solo (`settings.tower_channel_id`, 1485373559105655095) explique ce qu'on y fait, épinglé.

- **Textes** : [`channel_guide_embeds.py`](../../app/bot/embeds/channel_guide_embeds.py), écrits à partir des RÈGLES du code (horaires du raid de Monde › Rythme via `fight_label` / `close_label`, bonus d'équipe, réduction des gardes, niveau du premier raid = plus petit boss − `MARGIN`, constantes de `tower_service`) : un réglage changé, le texte suit. Bandeau `compose_channel_card` (même DA que le règlement).
- **Tenue** ([`channel_guides_cog.py`](../../app/bot/cogs/channel_guides_cog.py)) : toutes les 30 min (dès le démarrage), le guide est retrouvé à son pied de page `GUIDE_FOOTER` (épinglés, puis tête du salon), posté et épinglé s'il manque (la notice « a épinglé un message » est retirée), réécrit si son texte a changé (`same_panel` du règlement), réépinglé s'il ne l'est plus.
- Tests : [`test_channel_guides.py`](../../tests/bot/test_channel_guides.py).
