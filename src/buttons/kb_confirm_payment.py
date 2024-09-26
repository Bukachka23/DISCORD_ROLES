import discord
from discord import ButtonStyle, Interaction


class ConfirmPaymentView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.confirmed = False

    @discord.ui.button(label="I have completed the payment", style=ButtonStyle.primary)
    async def confirm_payment(self, interaction: Interaction, button: discord.ui.Button):
        self.confirmed = True
        await interaction.response.send_message(
            "Thank you for confirming your payment. Please upload your payment confirmation image along with the "
            "PaymentIntent ID in this channel.",
            ephemeral=True
        )
        self.stop()
