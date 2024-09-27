import discord
from discord import ButtonStyle, Interaction


class AmountSelectionView(discord.ui.View):
    def __init__(self, amounts):
        super().__init__(timeout=300)
        self.value = None
        for amount in amounts:
            button = AmountButton(amount)
            self.add_item(button)


class AmountButton(discord.ui.Button):
    def __init__(self, amount):
        super().__init__(label=f"${amount}", style=ButtonStyle.primary)
        self.amount = amount

    async def callback(self, interaction: Interaction):
        self.view.value = self.amount
        await interaction.response.send_message(f"You selected: ${self.amount}", ephemeral=True)
        self.view.stop()
