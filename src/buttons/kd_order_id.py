import discord
from discord import ButtonStyle, Interaction


class OrderIDView(discord.ui.View):
    """View for entering Order ID."""

    def __init__(self):
        super().__init__(timeout=300)
        self.value = None

    @discord.ui.button(label="Enter Order ID", style=ButtonStyle.primary)
    async def enter_order_id(
            self, interaction: Interaction, button: discord.ui.Button
    ) -> None:
        """Handle Order ID entry."""
        modal = OrderIDModal(title="Enter Order ID", view=self)
        await interaction.response.send_modal(modal)


class OrderIDModal(discord.ui.Modal):
    """Modal for entering Order ID."""

    def __init__(self, title: str, view: OrderIDView) -> None:
        super().__init__(title=title)
        self.view = view
        self.order_id_input = discord.ui.TextInput(
            label="Order ID",
            placeholder="Enter your Order ID",
            required=True,
            max_length=50,
        )
        self.add_item(self.order_id_input)

    async def on_submit(self, interaction: Interaction) -> None:
        """Handle modal submission."""
        order_id = self.order_id_input.value.strip()
        self.view.value = order_id
        await interaction.response.send_message(
            f"Order ID received: {order_id}", ephemeral=True
        )
        self.view.stop()
