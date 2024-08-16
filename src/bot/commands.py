import asyncio
import logging.config
import os
from datetime import datetime, timedelta
from typing import Any

import discord
from discord.ext import commands

from src.core.constants import ticket_states, ticket_info, TicketState, get_welcome_message, EnvVariables
from src.core.database import DatabaseManager, get_db
from src.core.models import User, Payment, Ticket
from src.core.utils import get_customer_by_email, get_active_subscription, calculate_remaining_days, \
    create_payment_intent
from src.config.log_config import LOGGING

logging.config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)


class CommandHandler(commands.Cog):
    def __init__(self, bot: commands.Bot, db_manager: DatabaseManager):
        self.bot = bot
        self.db_manager = db_manager
        super().__init__()
        logger.info("CommandHandler initialized")

    @commands.command(name='check_subscription')
    async def check_subscription(self, ctx):
        logger.info(f"Check subscription command invoked by user {ctx.author.id}")
        confirmation_message = await ctx.send("I've sent you a DM with instructions.")

        await confirmation_message.delete(delay=10)
        await ctx.author.send("Please enter your email:")

        def check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

        max_retries = 3
        for attempt in range(max_retries):
            try:
                email_msg = await self.bot.wait_for('message', check=check, timeout=120.0)
                email = email_msg.content
                customer = get_customer_by_email(email)
                if not customer:
                    await ctx.author.send("No customer found with the email.")
                    return

                subscription = get_active_subscription(customer)
                if not subscription:
                    await ctx.author.send("No active subscription found for the customer.")
                    return

                remaining_days = calculate_remaining_days(subscription)
                await ctx.author.send(f"You have {remaining_days} days left on your subscription.")
                logger.info(f"User {ctx.author.id} has {remaining_days} days left on subscription")
                break
            except asyncio.TimeoutError:
                if attempt < max_retries - 1:
                    await ctx.author.send(
                        f"You didn't respond in time. You have {max_retries - attempt - 1} more attempts.")
                else:
                    await ctx.author.send("You didn't respond in time. Please try the command again later.")
                    return
            except Exception as e:
                await ctx.author.send(f"An error occurred: {e!s}")
                logger.error(f"Error in check_subscription for user {ctx.author.id} ({ctx.author.name}): {e!s}",
                             exc_info=True)
                return

    @commands.command(name='renew_subscription')
    async def renew_subscription(self, ctx, days: int):
        logger.info(f"Renew subscription command invoked by user {ctx.author.id} for {days} days")
        confirmation_message = await ctx.send("I've sent you a DM with instructions.")

        await confirmation_message.delete(delay=10)
        await ctx.author.send("Please enter your email:")

        def check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)

        try:
            email_msg = await self.bot.wait_for('message', check=check, timeout=60.0)
            email = email_msg.content
            customer = get_customer_by_email(email)
            if not customer:
                await ctx.author.send("No customer found with the email.")
                return

            subscription = get_active_subscription(customer)
            if not subscription:
                await ctx.author.send("No active subscription found for the customer.")
                return

            remaining_days = calculate_remaining_days(subscription)
            new_end_date = datetime.now() + timedelta(days=days + remaining_days)
            await ctx.author.send(f"Your subscription has been renewed. New end date: {new_end_date}")
            logger.info(f"Subscription successfully renewed for user {ctx.author.id}. New end date: {new_end_date}")
        except Exception as e:
            await ctx.author.send(f"An error occurred: {e!s}")
            logger.error(f"Error in renew_subscription for user {ctx.author.id}: {e!s}", exc_info=True)

    @commands.command(name='delete_ticket')
    async def delete_ticket(self, ctx: commands.Context) -> None:
        """Delete a ticket for the user."""
        guild = ctx.guild
        member = ctx.author

        db = next(get_db())
        try:
            user = db.query(User).filter(User.discord_id == str(member.id)).first()
            if not user:
                await ctx.send(f'{member.mention}, you do not have any tickets.')
                return

            existing_ticket = db.query(Ticket).filter(Ticket.user_id == user.id, Ticket.closed_at.is_(None)).first()
            if not existing_ticket:
                await ctx.send(f'{member.mention}, you do not have any open tickets.')
                return

            ticket_channel = guild.get_channel(int(existing_ticket.channel_id))
            if ticket_channel:
                await ticket_channel.delete()

            existing_ticket.deleted_at = datetime.utcnow()
            db.commit()

            await ctx.send(f'{member.mention}, your ticket has been deleted.')
            logger.info(f"Deleted ticket channel {ticket_channel.name} for user {member}")
        except Exception as e:
            logger.error(f"Error deleting ticket: {e!s}")
            await ctx.send("An error occurred while deleting the ticket. Please try again later.")
        finally:
            db.close()

    @staticmethod
    async def create_ticket(ctx: commands.Context, user_id: str) -> None:
        """Create a ticket for the user."""
        guild = ctx.guild

        db = next(get_db())
        try:
            user = db.query(User).filter(User.discord_id == user_id).first()
            if not user:
                user = User(discord_id=user_id)
                db.add(user)
                db.commit()

            existing_ticket = db.query(Ticket).filter(Ticket.user_id == user.id, Ticket.closed_at.is_(None)).first()
            if existing_ticket:
                ticket_channel = guild.get_channel(int(existing_ticket.channel_id))
                if ticket_channel is None:
                    existing_ticket.deleted_at = datetime.utcnow()
                    db.commit()
                else:
                    await ctx.send(f'<@{user_id}>, you already have an open ticket: <#{existing_ticket.channel_id}>')
                    logger.info(f"User <@{user_id}> already has an open ticket: <#{existing_ticket.channel_id}>")
                    return

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                guild.get_member(int(user_id)): discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }

            member = guild.get_member(int(user_id))
            ticket_channel = await guild.create_text_channel(
                f'ticket-{member.name}-{member.discriminator}',
                overwrites=overwrites,
                category=discord.utils.get(guild.categories, name='TICKETS')
            )

            new_ticket = Ticket(channel_id=str(ticket_channel.id), user_id=user.id, created_at=datetime.utcnow())
            db.add(new_ticket)
            db.commit()

            await ticket_channel.send(
                f'<@{user_id}>, your ticket has been created. Please provide the following information:\n'
                f'1. Amount (in cents)\n'
                f'2. Currency (e.g., usd)\n'
                f'3. Order ID'
            )
            await ctx.send(f'<@{user_id}>, your ticket has been created: {ticket_channel.mention}')
            logger.info(f"Created ticket channel {ticket_channel.name} for user <@{user_id}>")
        except Exception as e:
            logger.error(f"Error creating ticket: {e!s}")
            await ctx.send("An error occurred while creating the ticket. Please try again later.")
        finally:
            db.close()

    @staticmethod
    async def process_ticket_info(message: discord.Message) -> None:
        """Process the ticket information provided by the user."""
        channel = message.channel
        author = message.author

        if author.id not in ticket_states:
            ticket_states[author.id] = TicketState.AWAITING_AMOUNT
            ticket_info[author.id] = {}
            await channel.send("Please provide the amount (in cents):")
            return

        state = ticket_states[author.id]

        try:
            if state == TicketState.AWAITING_AMOUNT:
                amount = int(message.content)
                ticket_info[author.id]['amount'] = amount
                ticket_states[author.id] = TicketState.AWAITING_CURRENCY
                await channel.send("Please provide the currency (e.g., usd):")
            elif state == TicketState.AWAITING_CURRENCY:
                currency = message.content.lower()
                if currency not in ['usd', 'eur', 'gbp']:
                    raise ValueError("Invalid currency")
                ticket_info[author.id]['currency'] = currency
                ticket_states[author.id] = TicketState.AWAITING_ORDER_ID
                await channel.send("Please provide the Order ID:")
            elif state == TicketState.AWAITING_ORDER_ID:
                order_id = message.content
                ticket_info[author.id]['order_id'] = order_id
                amount = ticket_info[author.id]['amount']
                currency = ticket_info[author.id]['currency']
                payment_intent = create_payment_intent(amount, currency, order_id)
                ticket_states[author.id] = TicketState.AWAITING_PAYMENT_CONFIRMATION
                await channel.send(
                    f'Your PaymentIntent ID is: {payment_intent.id}\n'
                    f'Please share your payment confirmation here by attaching an image and including the PaymentIntent'
                    f'ID in your message.'
                )
            else:
                await channel.send("Unexpected message. Please wait for further instructions.")

        except ValueError as e:
            await channel.send(f"Invalid input: {e!s}. Please try again.")
        except Exception as e:
            logger.error(f"Error in ticket information process: {e!s}")
            await channel.send("An error occurred during ticket information collection. Please try again later.")
            del ticket_states[author.id]
            if author.id in ticket_info:
                del ticket_info[author.id]

    async def check_payment(self, ctx: commands.Context) -> None:
        """
        Check the payment and assign the PREMIUM role based on the provided PaymentIntent ID and image attachment.
        """
        logger.info(f"Checking payment for user {ctx.author}")
        db = next(get_db())
        try:
            user = db.query(User).filter(User.discord_id == str(ctx.author.id)).first()
            if not user:
                await ctx.send(f'{ctx.author.mention}, you do not have any tickets.')
                return

            words = ctx.message.content.split()
            payment_intent_id = next((word for word in words if word.startswith('pi_')), None)

            if not ctx.message.attachments:
                await ctx.send('Please attach an image of your payment confirmation along with the PaymentIntent ID.')
                return

            attachment = ctx.message.attachments[0]
            if not attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                await ctx.send('Please attach a valid image file (PNG, JPG, JPEG, WEBP or GIF).')
                return

            image_url = attachment.url

            if not payment_intent_id:
                await ctx.send('Please provide a valid PaymentIntent ID starting with "pi_" along with the image.')
                return

            logger.info(f"Calling confirm_payment for user {ctx.author}")
            await self.confirm_payment(ctx, user, db, payment_intent_id, image_url)

        except Exception as e:
            logger.error(f"Error checking payment: {e!s}")
            await ctx.send('An error occurred while checking the payment. Please try again later.')
        finally:
            db.close()

    @staticmethod
    async def send_welcome_message(ctx: commands.Context, days: int = 30) -> None:
        """Send a welcome message to the user after confirming the payment."""
        welcome_message = get_welcome_message(ctx.author.name, days)
        await ctx.send(welcome_message)

    async def confirm_payment(self, ctx: commands.Context,
                              user: User,
                              db: Any,
                              payment_intent_id: str,
                              image_url: str) -> None:
        user.premium = True

        payment = Payment(
            user_id=user.id,
            payment_intent_id=payment_intent_id,
            confirmation_image=image_url,
            confirmed=True,
            created_at=datetime.utcnow()
        )
        db.add(payment)
        db.commit()

        premium_role_id = int(os.getenv(EnvVariables.PREMIUM_ROLE_ID.value))
        premium_role = ctx.guild.get_role(premium_role_id)

        if premium_role:
            try:
                await ctx.author.add_roles(premium_role)
                await ctx.send(f'Payment confirmed! {ctx.author.mention} has been granted the PREMIUM role.')
                logger.info(f"Granted PREMIUM role (ID: {premium_role_id}) to {ctx.author}")

                await self.send_welcome_message(ctx)
            except discord.errors.Forbidden:
                logger.error(f"Bot doesn't have permission to assign roles for user {ctx.author}")
                await ctx.send("Error: Bot doesn't have permission to assign roles. Please contact an admin.")
            except Exception as e:
                logger.error(f"Error assigning PREMIUM role to {ctx.author}: {e!s}")
                await ctx.send("An error occurred while assigning the PREMIUM role. Please contact an admin.")
        else:
            await ctx.send('Error: PREMIUM role not found. Please contact an admin.')
            logger.error(f"PREMIUM role not found. Searched for role ID: {premium_role_id}")
            logger.error(f"Available roles: {[role.name for role in ctx.guild.roles]}")

        await self.notify_admins(ctx, user, payment_intent_id, image_url)

    async def notify_admins(self, ctx: commands.Context,
                            user: User,
                            payment_intent_id: str,
                            image_url: str) -> None:
        """
        Notify admins about the new payment confirmation.
        """
        admin_channel_id = int(os.getenv(EnvVariables.ADMIN_USER_ID.value))

        admin_channel = ctx.guild.get_channel(admin_channel_id)

        if not admin_channel:
            for guild in self.bot.guilds:
                admin_channel = guild.get_channel(admin_channel_id)
                if admin_channel:
                    break

        if admin_channel:
            try:
                embed = discord.Embed(
                    title="New Payment Confirmation",
                    description=f"User: {ctx.author.mention}\nUser ID: {user.id}",
                    color=discord.Color.green()
                )
                if payment_intent_id:
                    embed.add_field(name="Payment Intent ID", value=payment_intent_id)
                if image_url:
                    embed.set_image(url=image_url)

                await admin_channel.send(embed=embed)
                logger.info(f"Notified admins about payment confirmation for user {ctx.author}")
            except discord.errors.Forbidden:
                logger.error(
                    f"Bot doesn't have permission to send messages in the admin channel (ID: {admin_channel_id})")
        else:
            logger.error(f"Admin notification channel not found. Searched for channel ID: {admin_channel_id}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Handle messages in ticket channels and detect ticket creation requests."""
        if message.author == self.bot.user:
            return

        if message.content.startswith(self.bot.command_prefix):
            return

        if isinstance(message.channel, discord.TextChannel):
            if message.channel.name.startswith('ticket-') and '-' in message.channel.name:
                if not message.content.startswith(self.bot.command_prefix):
                    logger.info(f"Processing message in ticket channel: {message.content}")
                    db = next(get_db())
                    try:
                        user = db.query(User).filter(User.discord_id == str(message.author.id)).first()
                        premium_role_id = int(os.getenv(EnvVariables.PREMIUM_ROLE_ID.value))
                        premium_role = message.guild.get_role(premium_role_id)

                        if user:
                            if premium_role in message.author.roles:
                                await message.channel.send(
                                    f'{message.author.mention}, you already have the PREMIUM role. No need to send '
                                    f'payment'
                                    f'confirmation again.')
                                logger.info(f"User {message.author} already has the PREMIUM role.")
                                return

                            existing_payment = db.query(Payment).filter(Payment.user_id == user.id,
                                                                        Payment.confirmed).first()
                            if existing_payment:
                                await message.channel.send(
                                    f'{message.author.mention}, your payment has already been confirmed. No need to '
                                    f'send'
                                    f'confirmation again.')
                                logger.info(f"User {message.author}'s payment has already been confirmed.")
                                return

                        words = message.content.split()
                        payment_intent_id = next((word for word in words if word.startswith('pi_')), None)

                        if payment_intent_id or message.attachments:
                            logger.info(f"Calling check_payment for user {message.author}")
                            await self.check_payment(await self.bot.get_context(message))
                        else:
                            await self.process_ticket_info(message)

                    except Exception as e:
                        logger.error(f"Error processing payment: {e!s}")
                        await message.channel.send('An error occurred while processing the payment. Please contact an '
                                                   'admin.')
                    finally:
                        db.close()
            elif message.content.lower() in ['payment verification', 'verify payment']:
                ctx = await self.bot.get_context(message)
                await self.create_ticket(ctx, str(message.author.id))
                return

        await self.bot.process_commands(message)
