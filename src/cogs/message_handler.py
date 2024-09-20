import logging.config
from typing import Optional

import discord
from discord.ext import commands

from src.cogs.payment import PaymentCog
from src.cogs.ticket import TicketCog
from src.config.logger import LOGGING


logging.config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)


class MessageHandler(commands.Cog):
    """Handles global message events."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("MessageHandlerCog initialized")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """
        Handle messages in ticket channels and detect payment confirmations.

        Args:
            message (discord.Message): The message sent in the guild.
        """
        if message.author == self.bot.user:
            return

        if message.content.startswith(self.bot.command_prefix):
            return

        ctx = await self.bot.get_context(message)

        if isinstance(message.channel, discord.TextChannel):
            if message.channel.name.startswith('ticket-'):
                if 'pi_' in message.content and message.attachments:
                    logger.info(f"Processing payment confirmation from user {message.author.id}")
                    payment_cog: Optional[PaymentCog] = self.bot.get_cog('PaymentCog')
                    if payment_cog:
                        await payment_cog.check_payment(ctx)
                    else:
                        logger.error("PaymentCog not found.")
            elif message.content.lower() in {'payment verification', 'verify payment'}:
                ticket_cog: Optional[TicketCog] = self.bot.get_cog('TicketCog')
                if ticket_cog:
                    await ticket_cog.create_ticket(ctx, str(message.author.id))
                else:
                    logger.error("TicketCog not found.")
                return

        await self.bot.process_commands(message)
