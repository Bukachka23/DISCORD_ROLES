import asyncio
import logging.config
from datetime import datetime

import discord
from discord.ext import commands

from src.config.logger import LOGGING
from src.core.database import get_db
from src.core.models import Ticket, User
from src.core.utils import create_payment_intent

logging.config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)


class TicketCog(commands.Cog):
    """Handles ticket creation and deletion."""

    def __init__(self, bot: commands.Bot, premium_role_id: int, admin_user_id: int):
        self.bot = bot
        self.premium_role_id = premium_role_id
        self.admin_user_id = admin_user_id
        logger.info("TicketCog initialized")

    @commands.command(name='delete_ticket')
    async def delete_ticket(self, ctx: commands.Context) -> None:
        """
        Delete the user's open ticket.

        Removes the ticket channel from Discord and updates the database accordingly.
        """
        logger.info(f"Delete ticket command invoked by user {ctx.author.id}")
        guild = ctx.guild
        member = ctx.author

        db = next(get_db())
        try:
            user = db.query(User).filter(User.discord_id == str(member.id)).first()
            if not user:
                await ctx.send(f"{member.mention}, you do not have any tickets.")
                return

            existing_ticket = db.query(Ticket).filter(
                Ticket.user_id == user.id,
                Ticket.closed_at.is_(None)
            ).first()

            if not existing_ticket:
                await ctx.send(f"{member.mention}, you do not have any open tickets.")
                return

            ticket_channel = guild.get_channel(int(existing_ticket.channel_id))
            if ticket_channel:
                await ticket_channel.delete()
                logger.info(f"Deleted ticket channel {ticket_channel.name} for user {member}")
            else:
                logger.warning(f"Ticket channel with ID {existing_ticket.channel_id} not found.")

            existing_ticket.deleted_at = datetime.utcnow()
            db.commit()

            await ctx.send(f"{member.mention}, your ticket has been deleted successfully. If you need further "
                           f"assistance, feel free to create a new ticket.")
        except Exception as e:
            logger.error(f"Error deleting ticket for user {ctx.author.id}: {e!s}", exc_info=True)
            await ctx.send("⚠️ **An error occurred** while deleting the ticket. Please try again later.")
        finally:
            db.close()

    @commands.command(name='start_payment')
    async def start_payment(self, ctx: commands.Context) -> None:
        """
        Start the payment verification process.

        Creates a support ticket for the user to begin payment verification.
        """
        logger.info(f"Start payment command invoked by user {ctx.author.id}")
        await self.create_ticket(ctx, str(ctx.author.id))

    async def create_ticket(self, ctx: commands.Context, user_id: str) -> None:
        """
        Create a ticket for the user and initiate the payment verification conversation.

        Args:
            ctx (commands.Context): The context of the command.
            user_id (str): The Discord user ID.
        """
        guild = ctx.guild
        db = next(get_db())

        try:
            user = db.query(User).filter(User.discord_id == user_id).first()
            if not user:
                user = User(discord_id=user_id)
                db.add(user)
                db.commit()
                logger.debug(f"Created new user in database with Discord ID {user_id}")

            existing_ticket = db.query(Ticket).filter(
                Ticket.user_id == user.id,
                Ticket.closed_at.is_(None)
            ).first()

            if existing_ticket:
                ticket_channel = guild.get_channel(int(existing_ticket.channel_id))
                if ticket_channel:
                    await ctx.send(
                        f"{ctx.author.mention}, you already have an open ticket: {ticket_channel.mention}\n"
                        "Please use this channel to continue your payment verification."
                    )
                    logger.info(f"User <@{user_id}> already has an open ticket: <#{existing_ticket.channel_id}>")
                    return
                else:
                    existing_ticket.deleted_at = datetime.utcnow()
                    db.commit()
                    logger.warning("Found ticket in database but channel does not exist. Marked as deleted.")

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                guild.get_member(int(user_id)): discord.PermissionOverwrite(
                    read_messages=True, send_messages=True
                ),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            }

            member = guild.get_member(int(user_id))
            if not member:
                await ctx.send(f"⚠️ **Member Not Found**\n\nMember with ID `{user_id}` not found in the guild.")
                logger.error(f"Member with ID {user_id} not found in guild.")
                return

            ticket_channel = await guild.create_text_channel(
                f'ticket-{member.name}-{member.discriminator}',
                overwrites=overwrites,
                category=discord.utils.get(guild.categories, name='TICKETS'),
                reason=f"Ticket created for user {member}"
            )
            logger.info(f"Created ticket channel {ticket_channel.name} for user <@{user_id}>")

            new_ticket = Ticket(
                channel_id=str(ticket_channel.id),
                user_id=user.id,
                created_at=datetime.utcnow(),
            )
            db.add(new_ticket)
            db.commit()

            await ticket_channel.send(
                f"{ctx.author.mention}, your ticket has been created. Let's start the **payment verification** "
                f"process.\n\n"
                "📌 **Next Steps:**\n"
                "1. Select your payment currency (USD, EUR, GBP).\n"
                "2. Enter the payment amount.\n"
                "3. Provide your Order ID.\n"
                "4. Share your payment confirmation image along with the PaymentIntent ID."
            )
            await ctx.send(f"{ctx.author.mention}, your ticket has been created: {ticket_channel.mention}\nPlease "
                           f"follow the instructions in the ticket to complete your payment verification.")

            await self.start_ticket_conversation(ticket_channel, user_id)

        except Exception as e:
            logger.error(f"Error creating ticket for user {user_id}: {e!s}", exc_info=True)
            await ctx.send("⚠️ **An error occurred** while creating the ticket. Please try again later.")
        finally:
            db.close()

    async def start_ticket_conversation(self, channel: discord.TextChannel, user_id: str) -> None:
        """
        Start the conversation with the user in the ticket channel to verify payment details.

        Args:
            channel (discord.TextChannel): The ticket channel.
            user_id (str): The Discord user ID.
        """

        def message_check(message: discord.Message) -> bool:
            return message.author.id == int(user_id) and message.channel == channel

        try:
            await channel.send(
                "**Step 1: Select Your Payment Currency**\n\n"
                "Please choose your payment currency from the following options:\n"
                "`USD`, `EUR`, `GBP`\n\n"
                "*Example:* `USD`"
            )

            while True:
                try:
                    msg = await self.bot.wait_for('message', check=message_check, timeout=120)
                    currency = msg.content.strip().upper()
                    if currency in {'USD', 'EUR', 'GBP'}:
                        break
                    await channel.send(
                        "❌ **Invalid Currency**\n\n"
                        "Please enter one of the following currencies: `USD`, `EUR`, `GBP`.\n\n"
                        "*Example:* `EUR`"
                    )
                except asyncio.TimeoutError:
                    await channel.send("⏰ **Session Timed Out**\n\nYou took too long to respond. Please start the "
                                       "process again if you wish to continue.")
                    return

            await channel.send(
                f"**Step 2: Enter the Payment Amount**\n\n"
                f"You have selected **{currency}** as your payment currency.\n"
                "Please enter the **amount** you wish to pay.\n\n"
                "*Example:* `59.95`"
            )

            while True:
                try:
                    msg = await self.bot.wait_for('message', check=message_check, timeout=120)
                    amount = float(msg.content.strip())
                    if amount > 0:
                        break
                    await channel.send(
                        "❌ **Invalid Amount**\n\n"
                        "The amount must be greater than zero.\n"
                        "Please enter a valid amount (e.g., `59.95`, `168.95`, `666.95`)."
                    )
                except ValueError:
                    await channel.send(
                        "❌ **Invalid Input**\n\n"
                        "Please enter a numerical value for the amount.\n\n"
                        "*Example:* `99.99`"
                    )
                except asyncio.TimeoutError:
                    await channel.send("⏰ **Session Timed Out**\n\nYou took too long to respond. Please start the "
                                       "process again if you wish to continue.")
                    return

            await channel.send(
                "**Step 3: Provide Your Order ID**\n\n"
                "Please enter your **Order ID** associated with this payment.\n\n"
                "*Example:* `ORD123456789`"
            )

            try:
                msg = await self.bot.wait_for('message', check=message_check, timeout=120)
                order_id = msg.content.strip()
                if not order_id:
                    await channel.send(
                        "❌ **Invalid Order ID**\n\n"
                        "Order ID cannot be empty. Please enter a valid Order ID.\n\n"
                        "*Example:* `ORD123456789`"
                    )
                    return
            except asyncio.TimeoutError:
                await channel.send("⏰ **Session Timed Out**\n\nYou took too long to respond. Please start the process "
                                   "again if you wish to continue.")
                return

            payment_intent = create_payment_intent(int(amount * 100), currency.lower(), order_id)
            await channel.send(
                f"**Step 4: Confirm Your Payment**\n\n"
                f"Your **PaymentIntent ID** is: `{payment_intent.id}`\n\n"
                "Please complete your payment using this PaymentIntent ID.\n"
                "Once the payment is complete, **share a screenshot** of your payment confirmation **image** along "
                "with the PaymentIntent ID in this channel.\n\n"
                "🔗 *Example:* `pi_1Hh1XYZAbCdEfGhIjKlMnOpQ`"
            )
            await channel.send(
                "💡 **Tips for Payment Confirmation:**\n"
                "- Ensure the PaymentIntent ID in your screenshot matches the one provided above.\n"
                "- Supported image formats: PNG, JPG, JPEG, WEBP, GIF.\n"
                "- If you encounter any issues, please contact support for assistance."
            )

        except Exception as e:
            await channel.send(
                f"⚠️ **An error occurred** during the payment verification process. Please try again later or contact "
                f"support.\n\n"
                f"**Error Details:** {e!s}"
            )
            logger.error(f"Error in start_ticket_conversation for channel {channel.id}: {e!s}", exc_info=True)
