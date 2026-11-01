"""Écran de `/admin lancer_saison` : l'aperçu de ce qui sera effacé, puis
une confirmation à TAPER (« SAISON 1 ») — un clic de trop ne doit pas
effacer une saison."""

from __future__ import annotations

import discord

from app.bot import season_launch
from app.shared.formatters import format_int

#: Tables de saison → libellé de l'aperçu (celles qui ne sont pas listées
#: sont vidées aussi, sans être détaillées).
_TABLE_LABELS = {
    "world_bosses": "world boss (instances et historique)",
    "active_events": "événements",
    "marketplace_listings": "annonces de brocante",
    "trades": "échanges",
    "role_trial_scores": "scores des défis",
    "offering_contributions": "dons à l'offrande",
}
_MONITORING = {"game_events": "événements du journal", "player_daily_snapshots": "photos des joueurs",
               "monitoring_alerts": "alertes"}


def build_preview_embed(preview: season_launch.Preview, season: int, ping: str) -> discord.Embed:
    report = preview.report
    cleared = report.cleared
    embed = discord.Embed(
        title=f"⚠️ Lancer la saison {season}",
        description=(
            "**Tout le monde repart de zéro** : seule l'identité Discord des joueurs reste. "
            "La base est sauvegardée juste avant ; il n'y a pas d'autre retour en arrière.\n"
            f"Pour confirmer, il faudra taper **{season_launch.confirmation(season)}**."
        ),
        color=discord.Color.orange(),
    )
    embed.add_field(
        name="👥 Joueurs remis à zéro",
        value=(f"**{report.players}** joueurs (jusqu'au niveau {report.max_level}) · "
               f"{format_int(report.gold_total)} or · {format_int(report.gear_total)} pièces d'équipement\n"
               "Niveaux, points, or, équipement, inventaire, arbre, titres, quêtes, tour, défis, "
               "affinités, essences et talents (nouveau tirage), maîtrise des artisans, cosmétiques, tutoriel."),
        inline=False,
    )
    tables = [f"{label} : {format_int(cleared[t])}" for t, label in _TABLE_LABELS.items() if cleared.get(t)]
    if cleared.get("offering_state"):
        tables.append("l'offrande repart de sa jauge de départ")
    embed.add_field(name="🧹 Vidé aussi",
                    value=" · ".join(tables) or "Rien en cours (boss, événements, brocante, échanges, défis, offrande).",
                    inline=False)
    monitoring = " · ".join(f"{format_int(cleared.get(t, 0))} {label}" for t, label in _MONITORING.items())
    embed.add_field(name="📊 Surveillance du site admin",
                    value=f"{monitoring}\nElle repart du lancement ; ses **réglages** (seuils, règles) sont gardés.",
                    inline=False)
    live = [f"{preview.encounters} combat(s) de zone annulé(s)" if preview.encounters else "",
            f"world boss **{preview.boss}** arrêté" if preview.boss else "",
            f"{preview.events} message(s) d'événement retiré(s)" if preview.events else ""]
    embed.add_field(name="🎭 Sur Discord",
                    value="Rangs remis au **Rang F** · commandes des joueurs fermées quelques secondes"
                          + "".join(f" · {x}" for x in live if x),
                    inline=False)
    embed.add_field(name="📣 Annonce",
                    value=("Dans le salon général, " + season_launch.PING_LABELS[ping]
                           if season_launch.PINGS.get(ping) is not None else "Aucune (changer avec l'option `annonce`)."),
                    inline=False)
    embed.set_footer(text="Restent : l'identité des joueurs, le contenu du jeu et les réglages du site "
                          "(rythme, offrande, alertes), le rôle @chad.")
    return embed


def build_result_embed(result: season_launch.LaunchResult) -> discord.Embed:
    failed = any(not ok for ok, _ in result.steps)
    embed = discord.Embed(
        title=f"🌸 Saison {result.season} lancée" + (" — à vérifier" if failed else ""),
        description="\n".join(f"{'✅' if ok else '⚠️'} {text}" for ok, text in result.steps),
        color=discord.Color.orange() if failed else season_launch.SEASON_COLOR,
    )
    if result.announcement_url:
        embed.add_field(name="📣 Annonce", value=f"[Voir le message]({result.announcement_url})", inline=False)
    if result.backup is not None:
        embed.set_footer(text=f"Sauvegarde complète : {result.backup}")
    return embed


class SeasonConfirmModal(discord.ui.Modal):
    def __init__(self, screen: SeasonLaunchView) -> None:
        super().__init__(title=f"Lancer la saison {screen.season}")
        self.screen = screen
        expected = season_launch.confirmation(screen.season)
        self.answer = discord.ui.TextInput(label=f"Tape « {expected} » pour confirmer",
                                           placeholder=expected, max_length=20)
        self.add_item(self.answer)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        expected = season_launch.confirmation(self.screen.season)
        if self.answer.value.strip().upper() != expected:
            await interaction.response.send_message(
                f"❌ Il fallait taper **{expected}** : rien n'a été fait.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.screen.close(f"⏳ Lancement de la saison {self.screen.season} en cours…")
        try:
            result = await season_launch.launch(interaction.client, self.screen.season, self.screen.ping)
        except season_launch.LaunchError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return
        await interaction.followup.send(embed=build_result_embed(result), ephemeral=True)


class SeasonLaunchView(discord.ui.View):
    def __init__(self, origin: discord.Interaction, season: int, ping: str) -> None:
        super().__init__(timeout=300)
        self.origin = origin
        self.season = season
        self.ping = ping
        self.launch_button.label = f"Lancer la saison {season}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.origin.user.id:
            await interaction.response.send_message("❌ Cette confirmation ne t'est pas destinée.", ephemeral=True)
            return False
        return True

    async def close(self, content: str) -> None:
        """Retire les boutons de l'aperçu (un seul lancement par aperçu)."""
        self.stop()
        try:
            await self.origin.edit_original_response(content=content, view=None)
        except discord.HTTPException:
            pass

    async def on_timeout(self) -> None:
        await self.close("⌛ Aperçu expiré : relance `/admin lancer_saison` si besoin.")

    @discord.ui.button(label="Lancer la saison", emoji="🌸", style=discord.ButtonStyle.danger)
    async def launch_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(SeasonConfirmModal(self))

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="Lancement annulé : rien n'a été fait.", embed=None, view=None)
