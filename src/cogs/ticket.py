import asyncio
import logging.config
from datetime import datetime
from typing import Optional

import discord
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.buttons.kb_amount_selection import AmountSelectionView
from src.buttons.kb_confirm_payment import ConfirmPaymentView
from src.buttons.kb_currency import CurrencyView
from src.buttons.kd_order_id import OrderIDView
from src.cogs.restart_payment import RestartPaymentView
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
        """Delete the user's open ticket."""
        logger.info(f"Delete ticket command invoked by user {ctx.author.id}")
        guild = ctx.guild
        member = ctx.author

        async with get_db() as db:
            try:
                user = await self.get_user(db, str(member.id))
                if not user:
                    await ctx.send(f"{member.mention}, you do not have any tickets.")
                    return

                existing_ticket = await self.get_existing_ticket(db, user.id)
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
                await db.commit()

                await ctx.send(f"{member.mention}, your ticket has been deleted successfully. "
                               "If you need further assistance, feel free to create a new ticket.")
            except Exception as e:
                logger.error(f"Error deleting ticket for user {ctx.author.id}: {e!s}", exc_info=True)
                await ctx.send("⚠️ **An error occurred** while deleting the ticket. Please try again later.")

    @commands.command(name='restart_payment')
    async def restart_payment(self, ctx: commands.Context) -> None:
        """Restart the payment verification process in the current ticket channel."""
        logger.info(f"Restart payment command invoked by user {ctx.author.id} in channel {ctx.channel.id}")
        channel = ctx.channel
        user_id = str(ctx.author.id)

        async with get_db() as db:
            try:
                user = await self.get_user(db, user_id)
                if not user:
                    await ctx.send("⚠️ You do not have an open ticket.")
                    return

                existing_ticket = await self.get_existing_ticket(db, user.id, channel.id)
                if not existing_ticket:
                    await ctx.send("⚠️ This is not your ticket channel.")
                    return

                await ctx.send("🔄 Restarting the payment verification process...")
                await self.start_ticket_conversation(channel, user_id)
            except Exception as e:
                logger.error(f"Error restarting payment for user {user_id}: {e!s}", exc_info=True)
                await ctx.send("⚠️ An error occurred while restarting the payment process. Please try again later.")

    @commands.command(name='start_payment')
    async def start_payment(self, ctx: commands.Context) -> None:
        """Start the payment verification process with interactive buttons."""
        logger.info(f"Start payment command invoked by user {ctx.author.id}")
        await self.create_ticket(ctx, str(ctx.author.id))

    async def create_ticket(self, ctx: commands.Context, user_id: str) -> None:
        """Create a ticket for the user and initiate the payment verification conversation."""
        guild = ctx.guild

        async with get_db() as db:
            try:
                user = await self.get_or_create_user(db, user_id)
                existing_ticket = await self.get_existing_ticket(db, user.id)

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
                        await db.commit()
                        logger.warning("Found ticket in database but channel does not exist. Marked as deleted.")

                ticket_channel = await self.create_ticket_channel(guild, ctx.author)
                new_ticket = Ticket(
                    channel_id=str(ticket_channel.id),
                    user_id=user.id,
                    created_at=datetime.utcnow(),
                )
                db.add(new_ticket)
                await db.commit()

                await ticket_channel.send(
                    f"{ctx.author.mention}, your ticket has been created. "
                    "Let's start the **payment verification** process.\n\n"
                    "Please keep the invoice received on email with you."
                )
                await ctx.send(f"{ctx.author.mention}, your ticket has been created: {ticket_channel.mention}\nPlease "
                               "follow the instructions in the ticket to complete your payment verification.")

                await self.start_ticket_conversation(ticket_channel, user_id)
            except Exception as e:
                logger.error(f"Error creating ticket for user {user_id}: {e!s}", exc_info=True)
                await ctx.send("⚠️ **An error occurred** while creating the ticket. Please try again later.")

    async def start_ticket_conversation(self, channel: discord.TextChannel, user_id: str) -> None:
        """Start the conversation with the user to verify payment details."""
        try:
            currency = await self.select_currency(channel, user_id)
            if not currency:
                return

            amount = await self.select_amount(channel, user_id, currency)
            if not amount:
                return

            order_id = await self.provide_order_id(channel, user_id)
            if not order_id:
                return

            payment_intent_id = await self.confirm_payment(channel, user_id, amount, currency, order_id)
            if not payment_intent_id:
                return

            payment_image_url = await self.upload_payment_confirmation(channel, user_id, payment_intent_id)
            if not payment_image_url:
                return

            restart_view = RestartPaymentView(self)

            await channel.send(
                "Thank you for submitting your payment confirmation. Our team will verify the payment shortly.\n\n"
                "If you need to make any changes or wish to start over, you can do so by clicking the button below.",
                view=restart_view
            )

            await self.notify_admins(
                channel, user_id, amount, currency, order_id, payment_intent_id, payment_image_url
            )
        except Exception as e:
            logger.error(f"Error in payment process for user {user_id}: {e}", exc_info=True)
            await channel.send("An error occurred during the payment process. Please contact support for assistance.")

    async def select_currency(self, channel: discord.TextChannel, user_id: str) -> Optional[str]:
        currency_view = CurrencyView()
        await channel.send(
            f"<@{user_id}>, **Step 1: Select Your Payment Currency**\n\n"
            "Please choose your payment currency from the following options:",
            view=currency_view
        )
        await currency_view.wait()
        if currency_view.value is None:
            await self.handle_timeout(channel, f"<@{user_id}> You didn't select a currency in time.")
            return None
        return currency_view.value

    async def select_amount(self, channel: discord.TextChannel, user_id: str, currency: str) -> Optional[float]:
        amounts = [59.95, 168.95, 666.95]
        amount_view = AmountSelectionView(amounts)
        await channel.send(
            f"<@{user_id}>,**Step 2: Select the Payment Amount**\n\n"
            f"You have selected **{currency}** as your payment currency.\n"
            "Please select the amount you have paid from the options below:",
            view=amount_view
        )
        await amount_view.wait()
        if amount_view.value is None:
            await self.handle_timeout(channel, "You didn't select an amount in time.")
            return None
        return amount_view.value

    async def provide_order_id(self, channel: discord.TextChannel, user_id: str) -> Optional[str]:
        order_id_view = OrderIDView()
        await channel.send(
            f"<@{user_id}>, **Step 3: Provide Your Order ID**\n\n"
            "Please click the button below to enter your **Order ID** associated with this payment.",
            view=order_id_view
        )
        await order_id_view.wait()
        if order_id_view.value is None:
            await self.handle_timeout(channel, "You didn't provide an Order ID in time.")
            return None
        return order_id_view.value

    async def confirm_payment(self, channel: discord.TextChannel, user_id: str, amount: float, currency: str,
                              order_id: str) -> Optional[str]:
        payment_intent = create_payment_intent(int(amount * 100), currency.lower(), order_id)
        await channel.send(
            f"<@{user_id}>, **Step 4: Confirm Your Payment**\n\n"
            f"Your **PaymentIntent ID** is: {payment_intent.id}\n\n"
            "Please complete your payment using this PaymentIntent ID."
        )

        confirm_payment_view = ConfirmPaymentView()
        await channel.send(
            "**Once the payment is complete, please click the button below to confirm.**",
            view=confirm_payment_view
        )
        await confirm_payment_view.wait()
        if not confirm_payment_view.confirmed:
            await self.handle_timeout(channel, "You didn't confirm your payment in time.")
            return None

        return payment_intent.id

    async def upload_payment_confirmation(self, channel: discord.TextChannel, user_id: str,
                                          payment_intent_id: str) -> Optional[str]:
        await channel.send(
            "Please upload your payment confirmation image along with the PaymentIntent ID in this channel.\n\n"
            "🔗 *Example:* pi_1Hh1XYZAbCdEfGhIjKlMnOpQ"
        )

        def payment_check(m):
            return m.author.id == int(user_id) and m.channel == channel and len(m.attachments) > 0

        try:
            payment_msg = await self.bot.wait_for('message', check=payment_check, timeout=300.0)
            payment_image = payment_msg.attachments[0]
            if payment_intent_id not in payment_msg.content:
                await channel.send("The PaymentIntent ID does not match. Please try again.")
                return None
            return payment_image.url
        except asyncio.TimeoutError:
            await self.handle_timeout(channel, "You didn't provide payment confirmation in time.")
            return None

    async def notify_admins(self, channel: discord.TextChannel, user_id: str, amount: float, currency: str,
                            order_id: str, payment_intent_id: str, image_url: str) -> None:
        """Notify admins about the new payment confirmation."""
        admin_channel = self.bot.get_channel(self.admin_user_id)

        if admin_channel:
            embed = discord.Embed(
                title="🆕 New Payment Confirmation",
                description=f"**User:** <@{user_id}>\n**Channel:** {channel.mention}",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Amount", value=f"{amount} {currency}", inline=True)
            embed.add_field(name="Order ID", value=order_id, inline=True)
            embed.add_field(name="PaymentIntent ID", value=payment_intent_id, inline=False)
            embed.set_image(url=image_url)

            await admin_channel.send(embed=embed)
            logger.info(f"Notified admins about payment confirmation for user {user_id}")
        else:
            logger.error(f"Admin notification channel not found. Searched for channel ID: {self.admin_user_id}")

    async def handle_timeout(self, channel: discord.TextChannel, message: str) -> None:
        """Handle timeouts and prompt the user to restart the process."""
        restart_view = RestartPaymentView(self)
        await channel.send(
            f"{message} Please start over if you wish to complete the payment process.",
            view=restart_view
        )

    @staticmethod
    async def get_user(db, discord_id: str) -> Optional[User]:
        """Retrieve a user from the database."""
        return db.query(User).filter(User.discord_id == str(discord_id)).first()

    async def get_or_create_user(self, db: AsyncSession, discord_id: str) -> User:
        """Get or create a user in the database."""
        result = await db.execute(select(User).filter(User.discord_id == str(discord_id)))
        user = result.scalar_one_or_none()
        if not user:
            user = User(discord_id=str(discord_id))
            db.add(user)
            await db.commit()
            logger.debug(f"Created new user in database with Discord ID {discord_id}")
        return user

    async def get_existing_ticket(self, db: AsyncSession, user_id: int, channel_id: Optional[int] = None) -> Optional[
        Ticket]:
        """Retrieve an existing ticket for a user."""
        query = select(Ticket).filter(
            Ticket.user_id == user_id,
            Ticket.closed_at.is_(None)
        )
        if channel_id:
            query = query.filter(Ticket.channel_id == str(channel_id))
        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def create_ticket_channel(guild: discord.Guild, member: discord.Member) -> discord.TextChannel:
        """Create a new ticket channel for the user."""
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        ticket_channel = await guild.create_text_channel(
            f'ticket-{member.name}-{member.discriminator}',
            overwrites=overwrites,
            category=discord.utils.get(guild.categories, name='TICKETS'),
            reason=f"Ticket created for user {member}"
        )
        logger.info(f"Created ticket channel {ticket_channel.name} for user {member.id}")
        return ticket_channel
