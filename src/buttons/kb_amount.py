import discord
from discord import ButtonStyle, Interaction


class AmountView(discord.ui.View):
    """View for selecting payment amount."""

    def __init__(self):
        super().__init__()
        self.value = None

    @discord.ui.button(label="Submit", style=ButtonStyle.primary)
    async def submit(
        self, interaction: Interaction, button: discord.ui.Button
    ) -> None:
        """Handle the submit button interaction."""
        modal = AmountModal(title="Enter Payment Amount", view=self)
        await interaction.response.send_modal(modal)


class AmountModal(discord.ui.Modal):
    """Modal for entering payment amount."""

    def __init__(self, title: str, view: AmountView) -> None:
        super().__init__(title=title)
        self.view = view
        self.amount_input = discord.ui.TextInput(
            label="Amount",
            placeholder="Enter the payment amount",
            required=True,
            max_length=10,
        )
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: Interaction) -> None:
        """Handle modal submission."""
        try:
            amount = float(self.amount_input.value)
            self.view.value = amount
            await interaction.response.send_message(
                f"You entered: {amount}", ephemeral=True
            )
            self.view.stop()
        except ValueError:
            await interaction.response.send_message(
                "Invalid amount entered. Please enter a valid number.",
                ephemeral=True,
            )
