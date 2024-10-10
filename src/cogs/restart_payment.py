import discord
from discord import ButtonStyle, Interaction


class RestartPaymentView(discord.ui.View):
    """View for restarting the payment process."""

    def __init__(self, ticket_cog):
        super().__init__(timeout=60)
        self.ticket_cog = ticket_cog

    @discord.ui.button(label="🔄 Start Over", style=ButtonStyle.danger)
    async def start_over(
        self, interaction: Interaction, button: discord.ui.Button
    ) -> None:
        """Handle restarting the payment process."""
        await interaction.response.send_message(
            "You have chosen to start over. Restarting the payment verification process...",
            ephemeral=True,
        )
        await self.ticket_cog.start_ticket_conversation(
            interaction.channel, str(interaction.user.id)
        )
        self.stop()
