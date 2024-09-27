import asyncio
import io
import logging.config
import os
from datetime import datetime
from typing import cast

import discord
from discord.ext import commands

from src.buttons.kb_amount_selection import AmountSelectionView
from src.buttons.kb_confirm_payment import ConfirmPaymentView
from src.buttons.kb_currency import CurrencyView
from src.buttons.kd_order_id import OrderIDView
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

            ticket_channel = guild.get_channel(int(existing_ticket.channel_id))  # type: ignore # noqa: E501
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

    @commands.command(name='restart_payment')
    async def restart_payment(self, ctx: commands.Context) -> None:
        """
        Restart the payment verification process in the current ticket channel.
        """
        logger.info(f"Restart payment command invoked by user {ctx.author.id} in channel {ctx.channel.id}")
        channel = ctx.channel
        user_id = str(ctx.author.id)

        db = next(get_db())
        try:
            user = db.query(User).filter(User.discord_id == user_id).first()
            if not user:
                await ctx.send("⚠️ You do not have an open ticket.")
                return

            existing_ticket = db.query(Ticket).filter(
                Ticket.user_id == user.id,
                Ticket.closed_at.is_(None),
                Ticket.channel_id == str(channel.id)
            ).first()

            if not existing_ticket:
                await ctx.send("⚠️ This is not your ticket channel.")
                return

            await ctx.send("🔄 Restarting the payment verification process...")
            await self.start_ticket_conversation(channel, user_id)

        except Exception as e:
            logger.error(f"Error restarting payment for user {user_id}: {e!s}", exc_info=True)
            await ctx.send("⚠️ An error occurred while restarting the payment process. Please try again later.")
        finally:
            db.close()

    @commands.command(name='start_payment')
    async def start_payment(self, ctx: commands.Context) -> None:
        """
        Start the payment verification process with interactive buttons.
        """
        logger.info(f"Start payment command invoked by user {ctx.author.id}")
        await self.create_ticket(ctx, str(ctx.author.id))

    async def create_ticket(self, ctx: commands.Context, user_id: str) -> None:
        """
        Create a ticket for the user and initiate the payment verification conversation.
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
                ticket_channel = guild.get_channel(int(existing_ticket.channel_id))  # type: ignore # noqa: E501
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
                guild.get_member(int(user_id)): discord.PermissionOverwrite(read_messages=True, send_messages=True),
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
                f"{ctx.author.mention}, your ticket has been created. "
                f"Let's start the **payment verification** process.\n\n"
                "Please keep the invoice received on email with you."
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
        """
        try:
            currency_view = CurrencyView()
            await channel.send(
                "**Step 1: Select Your Payment Currency**\n\n"
                "Please choose your payment currency from the following options:",
                view=currency_view
            )
            await currency_view.wait()
            if currency_view.value is None:
                await channel.send("You didn't select a currency in time. Please start over.")
                return

            currency = currency_view.value

            amounts = [59.95, 168.95, 666.95]
            amount_view = AmountSelectionView(amounts)
            await channel.send(
                f"**Step 2: Select the Payment Amount**\n\n"
                f"You have selected **{currency}** as your payment currency.\n"
                "Please select the amount you have paid from the options below:",
                view=amount_view
            )
            await amount_view.wait()
            if amount_view.value is None:
                await channel.send("You didn't select an amount in time. Please start over.")
                return

            amount = amount_view.value

            order_id_view = OrderIDView()
            embed = discord.Embed(
                title="**Step 3: Provide Your Order ID**",
                description="Please click the button below to enter your **Order ID** associated with this payment.",
                color=discord.Color.blue()
            )

            current_dir = os.path.dirname(os.path.abspath(__file__))
            image_path = os.path.join(current_dir, "..", "data", "pic.jpg")

            if not os.path.isfile(image_path):
                logger.error(f"Image file not found at path: {image_path}")
                await channel.send("An internal error occurred. Please contact support.")
                return

            with open(image_path, 'rb') as image_file:
                buffered_image_file = cast(io.BufferedIOBase, image_file)
                image = discord.File(buffered_image_file, filename="pic.jpg")
                embed.set_image(url="attachment://pic.jpg")
                await channel.send(file=image, embed=embed, view=order_id_view)

            await order_id_view.wait()
            if order_id_view.value is None:
                await channel.send("You didn't provide an Order ID in time. Please start over.")
                return

            order_id = order_id_view.value

            payment_intent = create_payment_intent(int(amount * 100), currency.lower(), order_id)
            await channel.send(
                f"**Step 4: Confirm Your Payment**\n\n"
                f"Your **PaymentIntent ID** is: `{payment_intent.id}`\n\n"
                "Please complete your payment using this PaymentIntent ID.",
            )

            confirm_payment_view = ConfirmPaymentView()
            await channel.send(
                "Once the payment is complete, please click the button below to confirm.",
                view=confirm_payment_view
            )
            await confirm_payment_view.wait()
            if not confirm_payment_view.confirmed:
                await channel.send("You didn't confirm your payment in time. Please start over.")
                return

            await channel.send(
                "Please upload your payment confirmation image along with the PaymentIntent ID in this channel.\n\n"
                "🔗 *Example:* `pi_1Hh1XYZAbCdEfGhIjKlMnOpQ`"
            )

            def payment_check(m):
                return m.author.id == int(user_id) and m.channel == channel and len(m.attachments) > 0

            try:
                payment_msg = await self.bot.wait_for('message', check=payment_check, timeout=300.0)
                payment_image = payment_msg.attachments[0]
                payment_intent_id = None
                for word in payment_msg.content.split():
                    if word.startswith('pi_'):
                        payment_intent_id = word
                        break

                if not payment_intent_id:
                    await channel.send("No valid PaymentIntent ID found in your message. Please try again.")
                    return

                await channel.send(
                    "Thank you for submitting your payment confirmation. Our team will verify the payment shortly."
                )

                await self.notify_admins(
                    channel, user_id, amount, currency, order_id, payment_intent_id, payment_image.url
                )

            except asyncio.TimeoutError:
                await channel.send(
                    "You didn't provide payment confirmation in time. "
                    "Please start over if you still wish to complete the payment."
                )
                return

        except Exception as e:
            logger.error(f"Error in payment process for user {user_id}: {e}", exc_info=True)
            await channel.send("An error occurred during the payment process. Please contact support for assistance.")

    async def notify_admins(self, channel: discord.TextChannel, user_id: str, amount: float, currency: str,
                            order_id: str, payment_intent_id: str, image_url: str) -> None:
        """
        Notify admins about the new payment confirmation.
        """
        admin_channel_id = self.admin_user_id
        admin_channel = self.bot.get_channel(admin_channel_id)

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
            logger.error(f"Admin notification channel not found. Searched for channel ID: {admin_channel_id}")
