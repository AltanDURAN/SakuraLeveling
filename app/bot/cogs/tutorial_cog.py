"""Cog `/tuto` : le tutoriel de Hana (31/10/2026, demande de l'auteur).

Premier choix : suivre le tutoriel ou le passer et commencer l'aventure tout
de suite. Le tutoriel raconte le bot en RP, étape par étape, avec des actions
à faire pour de vrai (vérifiées quand c'est possible) ; au bout, l'aventure
commence et Hana offre 3 potions du Grand Cerisier (100 % des PV), une seule
fois. Un panneau permanent dans le salon du tutoriel lance le même parcours.
Règles : `tutorial_service` ; progression : `use_cases/tutorial`.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from app.application.use_cases import tutorial
from app.bot.rank_roles import ensure_start_rank_role
from app.domain.services import tutorial_service as tsvc
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.encounters.farm_zone_loader import list_zones
from app.shared.paths import NPCS_ASSETS_DIR

_logger = logging.getLogger("sakura.tutorial")
_COLOR = discord.Color.from_rgb(240, 150, 190)
_PORTRAIT = NPCS_ASSETS_DIR / "hana.png"
PANEL_TITLE = "🌸 Bienvenue au Grand Cerisier"


def _first_zone() -> str:
    """Le salon de la première zone (rang F), pour le texte des étapes."""
    zone = next((z for z in list_zones() if z.get("rank") == "F" and z.get("channel_id")), None)
    return f"<#{zone['channel_id']}>" if zone else "la Clairière sinistre"


def _portrait() -> discord.File | None:
    return discord.File(_PORTRAIT, filename="hana.png") if _PORTRAIT.exists() else None


def _embed(title: str, text: str) -> discord.Embed:
    embed = discord.Embed(title=title, description=text, color=_COLOR)
    embed.set_author(name=tsvc.GUIDE_NAME)
    if _PORTRAIT.exists():
        embed.set_thumbnail(url="attachment://hana.png")
    return embed


def step_embed(index: int, warning: str = "") -> discord.Embed:
    step = tsvc.STEPS[index]
    zone = _first_zone()
    embed = _embed(f"{step.emoji} {step.title}", step.story.format(zone=zone))
    embed.add_field(name="🎯 À toi", value="\n".join(f"• {a.format(zone=zone)}" for a in step.actions),
                    inline=False)
    if step.check:
        embed.add_field(name="✅ Vérification",
                        value="Quand c'est fait, clique **C'est fait** : je vérifie. "
                              "Bloqué ? Tu peux passer l'étape.", inline=False)
    if warning:
        embed.add_field(name="⏳ Pas encore…", value=warning.format(zone=zone), inline=False)
    embed.set_footer(text=f"Étape {index + 1} / {len(tsvc.STEPS)} · ta progression est gardée : /tuto pour reprendre")
    return embed


def intro_embed(name: str, resume_at: int = 0, done: bool = False) -> discord.Embed:
    text = (f"Bienvenue, **{name}** ! Je suis Hana. Veux-tu que je te montre comment tout "
            "fonctionne ici ? Je te guiderai pas à pas — et à la fin, je t'offrirai "
            f"**{tsvc.REWARD_QUANTITY} potions du Grand Cerisier** (elles rendent 100 % de tes PV).\n\n"
            "Tu peux aussi passer le tutoriel et commencer l'aventure tout de suite.")
    if resume_at:
        text = (f"Te revoilà, **{name}** ! Nous en étions à l'étape **{resume_at + 1} / {len(tsvc.STEPS)}**. "
                "On reprend ?")
    if done:
        text = (f"Tu connais déjà le chemin, **{name}** ! Veux-tu tout revoir ? "
                "(La récompense ne se reçoit qu'une fois.)")
    return _embed("🌸 Le Grand Cerisier", text)


def adventure_embed(potions: int, skipped: bool) -> discord.Embed:
    zone = _first_zone()
    lines = [f"Ton aventure commence ! Le **Rang F** t'ouvre {zone} : va y combattre ton premier monstre.",
             "Les indispensables : **`/profil`**, **`/daily`**, **`/stats`**, **`/arbre`**, **`/quetes`**, "
             "et **`/help`** pour tout le reste."]
    if potions:
        lines.append(f"🎁 Tiens, pour la route : **{potions} × Potion du Grand Cerisier** (100 % des PV). "
                     "Bois-en une avec **`/utiliser`** quand tu es à bout de forces.")
    elif skipped:
        lines.append(f"Si tu changes d'avis, **`/tuto`** reprend le tutoriel — et ses "
                     f"{tsvc.REWARD_QUANTITY} potions t'attendent à la fin.")
    return _embed("🚀 L'aventure commence", "\n\n".join(lines))


def _player_id(user: discord.abc.User) -> int:
    with get_db_session() as session:
        profile = PlayerRepository(session).get_or_create_by_discord_id(
            discord_id=user.id, username=user.name, display_name=user.display_name)
        return profile.player.id


async def _send(interaction: discord.Interaction, embed: discord.Embed, view: discord.ui.View) -> None:
    file = _portrait()
    kwargs = {"embed": embed, "view": view, "ephemeral": True}
    if file is not None:
        kwargs["file"] = file
    await interaction.followup.send(**kwargs)


async def _edit(interaction: discord.Interaction, embed: discord.Embed, view: discord.ui.View | None) -> None:
    file = _portrait()
    await interaction.response.edit_message(embed=embed, view=view,
                                            attachments=[file] if file is not None else [])


class TutorialView(discord.ui.View):
    """Le tutoriel d'UN joueur (message éphémère)."""

    def __init__(self, player_id: int, step: int | None = None) -> None:
        super().__init__(timeout=1800)
        self.player_id = player_id
        self.step = step
        self._build()

    def _button(self, label: str, style, callback, emoji: str | None = None, disabled: bool = False):
        button = discord.ui.Button(label=label, style=style, emoji=emoji, disabled=disabled)
        button.callback = callback
        self.add_item(button)

    def _build(self) -> None:
        self.clear_items()
        if self.step is None:                                   # premier choix
            self._button("Suivre le tutoriel", discord.ButtonStyle.success, self._start, "📖")
            self._button("Passer et commencer l'aventure", discord.ButtonStyle.secondary, self._skip_all, "🚀")
            return
        step = tsvc.STEPS[self.step]
        self._button("Précédent", discord.ButtonStyle.secondary, self._previous, "◀️", disabled=self.step == 0)
        last = self.step == len(tsvc.STEPS) - 1
        if step.check:
            self._button("C'est fait", discord.ButtonStyle.success, self._verify, "✅")
            self._button("Passer l'étape", discord.ButtonStyle.secondary, self._next, "⏭️")
        elif not last:
            self._button("Suivant", discord.ButtonStyle.primary, self._next, "▶️")
        if last:
            self._button("Commencer l'aventure", discord.ButtonStyle.success, self._finish, "🚀")

    async def _show(self, interaction: discord.Interaction, step: int, warning: str = "") -> None:
        self.step = step
        await asyncio.to_thread(self._save, step)
        self._build()
        await _edit(interaction, step_embed(step, warning), self)

    def _save(self, step: int) -> None:
        with get_db_session() as session:
            tutorial.go_to(session, self.player_id, step)

    async def _start(self, interaction: discord.Interaction) -> None:
        await self._show(interaction, 0)

    async def _previous(self, interaction: discord.Interaction) -> None:
        await self._show(interaction, max(0, (self.step or 0) - 1))

    async def _next(self, interaction: discord.Interaction) -> None:
        if self.step == len(tsvc.STEPS) - 1:
            await self._finish(interaction)
            return
        await self._show(interaction, (self.step or 0) + 1)

    async def _verify(self, interaction: discord.Interaction) -> None:
        step = tsvc.STEPS[self.step]

        def run() -> bool:
            with get_db_session() as session:
                return tutorial.check(session, self.player_id, step)

        if await asyncio.to_thread(run):
            if self.step == len(tsvc.STEPS) - 1:
                await self._finish(interaction)
            else:
                await self._show(interaction, self.step + 1)
        else:
            await _edit(interaction, step_embed(self.step, step.hint), self)

    async def _start_adventure(self, interaction: discord.Interaction, *, finished: bool) -> None:
        def run() -> int:
            with get_db_session() as session:
                if finished:
                    return tutorial.finish(session, self.player_id)
                tutorial.skip(session, self.player_id)
                return 0

        potions = await asyncio.to_thread(run)
        if isinstance(interaction.user, discord.Member):
            await ensure_start_rank_role(interaction.user)
        self.stop()
        await _edit(interaction, adventure_embed(potions, skipped=not finished), None)

    async def _finish(self, interaction: discord.Interaction) -> None:
        await self._start_adventure(interaction, finished=True)

    async def _skip_all(self, interaction: discord.Interaction) -> None:
        await self._start_adventure(interaction, finished=False)


class ResumeView(TutorialView):
    """Retour au tutoriel : reprendre, recommencer, ou passer."""

    def __init__(self, player_id: int, resume_at: int) -> None:
        self.resume_at = resume_at
        super().__init__(player_id, None)

    def _build(self) -> None:
        if self.step is not None:
            super()._build()
            return
        self.clear_items()
        if self.resume_at:
            self._button(f"Reprendre (étape {self.resume_at + 1})", discord.ButtonStyle.success, self._resume, "▶️")
        self._button("Depuis le début", discord.ButtonStyle.primary, self._start, "📖")
        self._button("Commencer l'aventure", discord.ButtonStyle.secondary, self._skip_all, "🚀")

    async def _resume(self, interaction: discord.Interaction) -> None:
        await self._show(interaction, self.resume_at)


async def open_tutorial(interaction: discord.Interaction) -> None:
    """Ouvre le tutoriel du joueur (commande /tuto ou panneau du salon)."""
    await interaction.response.defer(ephemeral=True)

    def load():
        pid = _player_id(interaction.user)
        with get_db_session() as session:
            return pid, tutorial.state(session, pid)

    player_id, current = await asyncio.to_thread(load)
    name = interaction.user.display_name
    if current.status == "termine":
        view = ResumeView(player_id, 0)
        await _send(interaction, intro_embed(name, done=True), view)
    elif current.step > 0:
        await _send(interaction, intro_embed(name, resume_at=current.step), ResumeView(player_id, current.step))
    else:
        await _send(interaction, intro_embed(name), TutorialView(player_id))


class TutorialPanelView(discord.ui.View):
    """Panneau permanent du salon du tutoriel (survit aux redémarrages)."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Commencer le tutoriel", style=discord.ButtonStyle.success, emoji="🌸",
                       custom_id="tutorial:open")
    async def open(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await open_tutorial(interaction)


def panel_embed() -> discord.Embed:
    return discord.Embed(
        title=PANEL_TITLE,
        description=("Nouveau venu ? **Hana**, la gardienne du Grand Cerisier, te fait découvrir le "
                     "jeu en quelques minutes : combats, butin, arbre, éléments, ville, rangs…\n\n"
                     f"Va jusqu'au bout et elle t'offre **{tsvc.REWARD_QUANTITY} potions du Grand Cerisier** "
                     "(100 % des PV). Pressé ? Tu peux passer le tutoriel et commencer l'aventure tout de suite.\n\n"
                     "Clique ci-dessous, ou tape **`/tuto`**."),
        color=_COLOR)


class TutorialCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.add_view(TutorialPanelView())
        self._panel_task = asyncio.ensure_future(self._ensure_panel())

    def cog_unload(self) -> None:
        self._panel_task.cancel()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """/tuto : dans le salon du tutoriel ou les salons de commandes."""
        if interaction.channel_id in {settings.tutorial_channel_id, *settings.command_channel_ids}:
            return True
        where = f"<#{settings.tutorial_channel_id}>" if settings.tutorial_channel_id else "le salon général"
        await interaction.response.send_message(f"🌸 Le tutoriel se lance dans {where}.", ephemeral=True)
        return False

    async def _ensure_panel(self) -> None:
        """Poste le panneau dans le salon du tutoriel s'il n'y est pas déjà."""
        await self.bot.wait_until_ready()
        channel = self.bot.get_channel(settings.tutorial_channel_id) if settings.tutorial_channel_id else None
        if channel is None:
            return
        try:
            async for message in channel.history(limit=30):
                if message.author.id == self.bot.user.id and any(e.title == PANEL_TITLE for e in message.embeds):
                    return
            await channel.send(embed=panel_embed(), view=TutorialPanelView())
        except discord.HTTPException:
            _logger.warning("panneau du tutoriel impossible dans %s", settings.tutorial_channel_id, exc_info=True)

    @app_commands.command(name="tuto", description="Le tutoriel : découvre le jeu avec Hana (3 potions à la clé)")
    async def tuto(self, interaction: discord.Interaction) -> None:
        await open_tutorial(interaction)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TutorialCog(bot))
