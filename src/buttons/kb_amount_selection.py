import discord
from discord import ButtonStyle, Interaction


class AmountSelectionView(discord.ui.View):
    """View for selecting payment amount from predefined options."""

    def __init__(self, amounts: list[float]):
        super().__init__(timeout=300)
        self.value = None
        for amount in amounts:
            button = AmountButton(amount)
            self.add_item(button)


class AmountButton(discord.ui.Button):
    """Button representing a specific payment amount."""

    def __init__(self, amount: float):
        super().__init__(
            label=f"${amount}", style=ButtonStyle.primary
        )
        self.amount = amount

    async def callback(self, interaction: Interaction) -> None:
        """Handle button click."""
        self.view.value = self.amount
        await interaction.response.send_message(
            f"You selected: ${self.amount}", ephemeral=True
        )
        self.view.stop()
