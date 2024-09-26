import discord
from discord import ButtonStyle, Interaction


class AmountView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.value = None

    @discord.ui.button(label="Submit", style=ButtonStyle.primary)
    async def submit(self, interaction: Interaction, button: discord.ui.Button):
        modal = AmountModal(title="Enter Payment Amount", view=self)
        await interaction.response.send_modal(modal)


class AmountModal(discord.ui.Modal):
    def __init__(self, *args, view: AmountView, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.view = view

        self.amount_input = discord.ui.TextInput(label="Amount")
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: Interaction) -> None:
        try:
            amount = float(self.amount_input.value)
            self.view.value = amount
            await interaction.response.send_message(f"You entered: {amount}", ephemeral=True)
            self.view.stop()
        except ValueError:
            await interaction.response.send_message(
                "Invalid amount entered. Please enter a valid number.",
                ephemeral=True
            )
