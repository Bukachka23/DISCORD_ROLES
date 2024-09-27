import discord
from discord import ButtonStyle, Interaction


class OrderIDView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.value = None

    @discord.ui.button(label="Enter Order ID", style=ButtonStyle.primary)
    async def enter_order_id(self, interaction: Interaction, button: discord.ui.Button):
        modal = OrderIDModal(title="Enter Order ID", view=self)
        await interaction.response.send_modal(modal)


class OrderIDModal(discord.ui.Modal):
    def __init__(self, *args, view: OrderIDView, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.view = view

        self.order_id_input = discord.ui.TextInput(label="Order ID")
        self.add_item(self.order_id_input)

    async def on_submit(self, interaction: Interaction) -> None:
        self.view.value = self.order_id_input.value.strip()
        await interaction.response.send_message(f"Order ID received: {self.view.value}", ephemeral=True)
        self.view.stop()
