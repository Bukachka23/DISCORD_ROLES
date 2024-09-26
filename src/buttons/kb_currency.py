import discord
from discord import ButtonStyle, Interaction


class CurrencyView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.value = None

    @discord.ui.button(label="USD", style=ButtonStyle.primary)
    async def usd(self, interaction: Interaction, button: discord.ui.Button):
        self.value = "USD"
        await interaction.response.send_message("You selected USD.", ephemeral=True)
        self.stop()

    @discord.ui.button(label="EUR", style=ButtonStyle.primary)
    async def eur(self, interaction: Interaction, button: discord.ui.Button):
        self.value = "EUR"
        await interaction.response.send_message("You selected EUR.", ephemeral=True)
        self.stop()

    @discord.ui.button(label="GBP", style=ButtonStyle.primary)
    async def gbp(self, interaction: Interaction, button: discord.ui.Button):
        self.value = "GBP"
        await interaction.response.send_message("You selected GBP.", ephemeral=True)
        self.stop()
