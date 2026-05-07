"""View de confirmation pour `/craft_panoplie` et `/forge_panoplie`.

Affiche un récap des pièces qui vont être crafted/forged et des
ingrédients consommés. 2 boutons : Confirmer (vert) et Annuler (gris).

Le View ne fonctionne QUE pour l'utilisateur initial (le `viewer_id`
passé au constructeur). Les autres voient les boutons mais reçoivent
"❌ Cette confirmation n'est pas pour vous." s'ils cliquent.
"""

from __future__ import annotations

import discord

from app.application.use_cases.panoplie_crafts import (
    ExecutePanoplieCraftsUseCase,
    PanoplieCraftPlan,
)
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session


_VERB_PAST = {"craft": "craftée(s)", "forge": "forgée(s)"}
_VERB_BUTTON = {"craft": "Crafter", "forge": "Forger"}


def build_plan_embed(plan: PanoplieCraftPlan) -> discord.Embed:
    """Embed récap (preview) du plan : pièces à craft + ingrédients."""
    color = (
        discord.Color.red() if plan.station == "forge"
        else discord.Color.orange()
    )
    title = (
        f"🔥 Forge — Panoplie {plan.family_icon} {plan.family_name}"
        if plan.station == "forge"
        else f"🛠️ Craft — Panoplie {plan.family_icon} {plan.family_name}"
    )
    embed = discord.Embed(title=title, color=color)

    if plan.is_empty:
        embed.description = (
            "_Vous possédez déjà toutes les pièces craftables de cette "
            "panoplie sur cette station, ou aucune n'a de recette._"
        )
        return embed

    # Liste des pièces à crafter
    pieces_lines = []
    for entry in plan.entries:
        pieces_lines.append(f"• **{entry.result_item.name}**")
    embed.add_field(
        name=f"🧩 Pièces à produire ({len(plan.entries)})",
        value="\n".join(pieces_lines)[:1024],
        inline=False,
    )

    # Liste des ingrédients : ce dont j'ai besoin / ce que j'ai
    ingredients_lines = []
    for code in sorted(plan.total_ingredients.keys()):
        needed = plan.total_ingredients[code]
        owned = plan.inventory_qty.get(code, 0)
        item = plan.item_lookup.get(code)
        name = item.name if item else code
        if owned >= needed:
            mark = "✅"
            status = f"{owned}/{needed}"
        else:
            mark = "❌"
            status = f"**{owned}/{needed}** (manque {needed - owned})"
        ingredients_lines.append(f"{mark} {name} — {status}")

    embed.add_field(
        name="📦 Ingrédients requis",
        value="\n".join(ingredients_lines)[:1024],
        inline=False,
    )

    if not plan.sufficient:
        embed.set_footer(
            text="❌ Ressources insuffisantes — récolte ce qui manque.",
        )
    else:
        verb = _VERB_BUTTON[plan.station]
        embed.set_footer(
            text=f"✅ Toutes les ressources sont là — clique sur {verb} pour confirmer.",
        )

    if plan.already_owned:
        owned_lines = "\n".join(
            f"• ~~{it.name}~~" for it in plan.already_owned[:8]
        )
        suffix = (
            f"\n_… et {len(plan.already_owned) - 8} autres_"
            if len(plan.already_owned) > 8 else ""
        )
        embed.add_field(
            name=f"🛍️ Déjà possédé(s) ({len(plan.already_owned)})",
            value=(owned_lines + suffix) or "—",
            inline=False,
        )

    return embed


class PanoplieCraftConfirmView(discord.ui.View):
    def __init__(
        self,
        plan: PanoplieCraftPlan,
        viewer_id: int,
        username: str,
        display_name: str,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.plan = plan
        self.viewer_id = viewer_id
        self.username = username
        self.display_name = display_name
        self.confirmed = False

        # Bouton confirm — désactivé si plan vide ou ressources insuffisantes
        self.confirm_btn.label = _VERB_BUTTON[plan.station]
        if plan.is_empty or not plan.sufficient:
            self.confirm_btn.disabled = True

    async def interaction_check(
        self, interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id != self.viewer_id:
            await interaction.response.send_message(
                "❌ Cette confirmation n'est pas pour vous.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Confirmer", style=discord.ButtonStyle.success, emoji="✅",
    )
    async def confirm_btn(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        # Re-disable to prevent double-click
        button.disabled = True
        self.cancel_btn.disabled = True
        self.confirmed = True

        with get_db_session() as session:
            use_case = ExecutePanoplieCraftsUseCase(
                player_repository=PlayerRepository(session),
                inventory_repository=InventoryRepository(session),
                item_repository=ItemRepository(session),
            )
            result = use_case.execute(
                discord_id=self.viewer_id,
                username=self.username,
                display_name=self.display_name,
                plan=self.plan,
            )

        embed = discord.Embed(
            title=result.message,
            color=(
                discord.Color.green() if result.success
                else discord.Color.red()
            ),
        )
        if result.crafted_items:
            embed.description = "\n".join(
                f"• **{name}**" for name in result.crafted_items
            )

        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    @discord.ui.button(
        label="Annuler", style=discord.ButtonStyle.secondary, emoji="✖️",
    )
    async def cancel_btn(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        embed = discord.Embed(
            title="✖️ Craft annulé",
            description="Aucun ingrédient consommé.",
            color=discord.Color.dark_gray(),
        )
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()
