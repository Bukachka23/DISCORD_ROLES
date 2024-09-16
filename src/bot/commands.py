import asyncio
import logging.config
import os
from datetime import datetime, timedelta
from typing import Any

import discord
from discord.ext import commands

from src.config.logger import LOGGING
from src.core.constants import get_welcome_message, EnvVariables
from src.core.database import get_db
from src.core.models import User, Payment, Ticket
from src.core.utils import (
    get_customer_by_email,
    get_active_subscription,
    calculate_remaining_days,
    create_payment_intent,
)


logging.config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)


class CommandHandler(commands.Cog):
    """Handles all bot commands related to subscriptions, payments, and tickets."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()
        logger.info("CommandHandler initialized")

    @commands.command(name='check_subscription')
    async def check_subscription(self, ctx: commands.Context) -> None:
        """
        Check the user's subscription status.

        Sends a DM to the user requesting their email to verify subscription details.
        """
        logger.info(f"Check subscription command invoked by user {ctx.author.id}")
        confirmation_message = await ctx.send("I've sent you a DM with instructions.")
        await confirmation_message.delete(delay=10)

        await ctx.author.send(
            "Hey Foxian! "
            "To confirm your details, please share the email ID with which you "
            "have purchased our premium plan."
        )

        def dm_check(message: discord.Message) -> bool:
            return message.author == ctx.author and isinstance(message.channel, discord.DMChannel)

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                email_message = await self.bot.wait_for('message', check=dm_check, timeout=120.0)
                email = email_message.content.strip()
                customer = get_customer_by_email(email)

                if not customer:
                    await ctx.author.send("No customer found with that email.")
                    return

                subscription = get_active_subscription(customer)
                if not subscription:
                    await ctx.author.send("No active subscription found for that customer.")
                    return

                remaining_days = calculate_remaining_days(subscription)
                await ctx.author.send(f"You have {remaining_days} days left on your subscription.")
                logger.info(f"User {ctx.author.id} has {remaining_days} days left on subscription")
                break

            except asyncio.TimeoutError:
                if attempt < max_retries:
                    await ctx.author.send(
                        f"You didn't respond in time. You have {max_retries - attempt} more attempts."
                    )
                else:
                    await ctx.author.send("You didn't respond in time. Please try the command again later.")
                    return

            except Exception as e:
                await ctx.author.send(f"An error occurred: {e!s}")
                logger.error(
                    f"Error in check_subscription for user {ctx.author.id} ({ctx.author}): {e!s}",
                    exc_info=True,
                )
                return

    @commands.command(name='renew_subscription')
    async def renew_subscription(self, ctx: commands.Context, days: int) -> None:
        """
        Renew the user's subscription for a specified number of days.

        Args:
            days (int): Number of days to extend the subscription.
            :param days: The number of days to extend the subscription.
            :param ctx: The context of the command.
        """
        logger.info(f"Renew subscription command invoked by user {ctx.author.id} for {days} days")
        confirmation_message = await ctx.send("I've sent you a DM with instructions.")
        await confirmation_message.delete(delay=10)

        await ctx.author.send("Please enter your email:")

        def dm_check(message: discord.Message) -> bool:
            return message.author == ctx.author and isinstance(message.channel, discord.DMChannel)

        try:
            email_message = await self.bot.wait_for('message', check=dm_check, timeout=60.0)
            email = email_message.content.strip()
            customer = get_customer_by_email(email)

            if not customer:
                await ctx.author.send("No customer found with that email.")
                return

            subscription = get_active_subscription(customer)
            if not subscription:
                await ctx.author.send("No active subscription found for that customer.")
                return

            remaining_days = calculate_remaining_days(subscription)
            new_end_date = datetime.utcnow() + timedelta(days=days + remaining_days)
            db = next(get_db())
            user = db.query(User).filter(User.discord_id == str(ctx.author.id)).first()
            if user:
                user.subscription_end = new_end_date
                db.commit()
                await ctx.author.send(f"Your subscription has been renewed. New end date: {new_end_date.date()}")
                logger.info(f"Subscription successfully renewed for user {ctx.author.id}. New end date: {new_end_date}")
            else:
                await ctx.author.send("User not found in the database.")
                logger.warning(f"User {ctx.author.id} not found in database during renewal.")

        except asyncio.TimeoutError:
            await ctx.author.send("You didn't respond in time. Please try the command again later.")
            return

        except Exception as e:
            await ctx.author.send(f"An error occurred: {e!s}")
            logger.error(f"Error in renew_subscription for user {ctx.author.id}: {e!s}", exc_info=True)

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
                await ctx.send(f'{member.mention}, you do not have any tickets.')
                return

            existing_ticket = db.query(Ticket).filter(
                Ticket.user_id == user.id,
                Ticket.closed_at.is_(None)
            ).first()

            if not existing_ticket:
                await ctx.send(f'{member.mention}, you do not have any open tickets.')
                return

            ticket_channel = guild.get_channel(int(existing_ticket.channel_id))
            if ticket_channel:
                await ticket_channel.delete()
                logger.info(f"Deleted ticket channel {ticket_channel.name} for user {member}")
            else:
                logger.warning(f"Ticket channel with ID {existing_ticket.channel_id} not found.")

            existing_ticket.deleted_at = datetime.utcnow()
            db.commit()

            await ctx.send(f'{member.mention}, your ticket has been deleted.')

        except Exception as e:
            logger.error(f"Error deleting ticket for user {ctx.author.id}: {e!s}", exc_info=True)
            await ctx.send("An error occurred while deleting the ticket. Please try again later.")

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
                        f'{ctx.author.mention}, you already have an open ticket: {ticket_channel.mention}'
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
                await ctx.send(f"Member with ID {user_id} not found in guild.")
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
                f'{ctx.author.mention}, your ticket has been created. Let\'s start the verification process.'
            )
            await ctx.send(f'{ctx.author.mention}, your ticket has been created: {ticket_channel.mention}')

            await self.start_ticket_conversation(ticket_channel, user_id)

        except Exception as e:
            logger.error(f"Error creating ticket for user {user_id}: {e!s}", exc_info=True)
            await ctx.send("An error occurred while creating the ticket. Please try again later.")

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
            await channel.send("Please select your payment currency. Options: USD, EUR, GBP")

            while True:
                try:
                    msg = await self.bot.wait_for('message', check=message_check, timeout=120)
                    currency = msg.content.strip().upper()
                    if currency in {'USD', 'EUR', 'GBP'}:
                        break
                    await channel.send("Invalid currency. Please enter one of: USD, EUR, GBP")
                except asyncio.TimeoutError:
                    await channel.send("You took too long to respond. Please start the process again.")
                    return

            await channel.send(f"Selected currency: {currency}. Please enter the amount.")

            while True:
                try:
                    msg = await self.bot.wait_for('message', check=message_check, timeout=120)
                    amount = float(msg.content.strip())
                    if amount > 0:
                        break
                    await channel.send("Amount must be greater than zero. "
                                       "Please enter a valid amount(for example 59.95, 168.95, 666.95 .")
                except ValueError:
                    await channel.send("Invalid amount. Please enter a number.")
                except asyncio.TimeoutError:
                    await channel.send("You took too long to respond. Please start the process again.")
                    return

            await channel.send(f"Amount: {amount}. Please enter your Order ID.")

            try:
                msg = await self.bot.wait_for('message', check=message_check, timeout=120)
                order_id = msg.content.strip()
            except asyncio.TimeoutError:
                await channel.send("You took too long to respond. Please start the process again.")
                return

            payment_intent = create_payment_intent(int(amount * 100), currency.lower(), order_id)
            await channel.send(
                f'Your PaymentIntent ID is: {payment_intent.id}\n'
                'Please share your payment confirmation here by attaching an image and including the PaymentIntent '
                'ID in your message.'
            )

        except Exception as e:
            await channel.send(f"An error occurred: {e!s}")
            logger.error(f"Error in start_ticket_conversation for channel {channel.id}: {e!s}", exc_info=True)

    @commands.command(name='check_payment')
    async def check_payment(self, ctx: commands.Context) -> None:
        """
        Check the payment and assign the PREMIUM role based on the provided PaymentIntent ID and image attachment.

        This command is triggered automatically when a message in a ticket channel contains a PaymentIntent ID.
        """
        logger.info(f"Checking payment for user {ctx.author.id}")
        db = next(get_db())

        try:
            user = db.query(User).filter(User.discord_id == str(ctx.author.id)).first()
            if not user:
                await ctx.send(f'{ctx.author.mention}, you do not have any tickets.')
                return

            words = ctx.message.content.split()
            payment_intent_id = next((word for word in words if word.startswith('pi_')), None)

            if not ctx.message.attachments:
                await ctx.send(
                    'Please attach an image of your payment confirmation along with the PaymentIntent ID.'
                )
                return

            attachment = ctx.message.attachments[0]
            if not attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                await ctx.send('Please attach a valid image file (PNG, JPG, JPEG, WEBP, or GIF).')
                return

            image_url = attachment.url

            if not payment_intent_id:
                await ctx.send('Please provide a valid PaymentIntent ID starting with "pi_" along with the image.')
                return

            logger.info(f"Calling confirm_payment for user {ctx.author.id}")
            await self.confirm_payment(ctx, user, db, payment_intent_id, image_url)

        except Exception as e:
            logger.error(f"Error checking payment for user {ctx.author.id}: {e!s}", exc_info=True)
            await ctx.send('An error occurred while checking the payment. Please try again later.')

        finally:
            db.close()

    async def confirm_payment(
        self,
        ctx: commands.Context,
        user: User,
        db: Any,
        payment_intent_id: str,
        image_url: str,
    ) -> None:
        """
        Confirm the payment and assign the PREMIUM role to the user.

        Args:
            ctx (commands.Context): The context of the command.
            user (User): The user object from the database.
            db (Any): The database session.
            payment_intent_id (str): The Stripe PaymentIntent ID.
            image_url (str): URL of the payment confirmation image.
        """
        try:
            user.premium = True

            payment = Payment(
                user_id=user.id,
                payment_intent_id=payment_intent_id,
                confirmation_image=image_url,
                confirmed=True,
                created_at=datetime.utcnow(),
            )
            db.add(payment)
            db.commit()

            premium_role_id = int(os.getenv(EnvVariables.PREMIUM_ROLE_ID.value))
            premium_role = ctx.guild.get_role(premium_role_id)

            if premium_role:
                try:
                    await ctx.author.add_roles(premium_role)
                    await ctx.send(f'Payment confirmed! {ctx.author.mention} has been granted the PREMIUM role.')
                    logger.info(f"Granted PREMIUM role (ID: {premium_role_id}) to {ctx.author.id}")

                    await self.send_welcome_message(ctx)
                except discord.errors.Forbidden:
                    logger.error(f"Bot lacks permissions to assign roles to user {ctx.author.id}")
                    await ctx.send("Error: Bot doesn't have permission to assign roles. Please contact an admin.")
                except Exception as e:
                    logger.error(f"Error assigning PREMIUM role to {ctx.author.id}: {e!s}", exc_info=True)
                    await ctx.send("An error occurred while assigning the PREMIUM role. Please contact an admin.")
            else:
                await ctx.send('Error: PREMIUM role not found. Please contact an admin.')
                logger.error(f"PREMIUM role not found. Searched for role ID: {premium_role_id}")

            await self.notify_admins(ctx, user, payment_intent_id, image_url)

        except Exception as e:
            logger.error(f"Error in confirm_payment for user {ctx.author.id}: {e!s}", exc_info=True)
            await ctx.send("An error occurred while confirming your payment. Please contact an admin.")

    @staticmethod
    async def send_welcome_message(ctx: commands.Context, days: int = 30) -> None:
        """
        Send a welcome message to the user after confirming the payment.

        Args:
            ctx (commands.Context): The context of the command.
            days (int, optional): Number of days the PREMIUM role is valid. Defaults to 30.
        """
        welcome_message = get_welcome_message(ctx.author.name, days)
        await ctx.send(welcome_message)

    async def notify_admins(
        self,
        ctx: commands.Context,
        user: User,
        payment_intent_id: str,
        image_url: str,
    ) -> None:
        """
        Notify admins about the new payment confirmation.

        Args:
            ctx (commands.Context): The context of the command.
            user (User): The user who made the payment.
            payment_intent_id (str): The Stripe PaymentIntent ID.
            image_url (str): URL of the payment confirmation image.
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
                    color=discord.Color.green(),
                )
                if payment_intent_id:
                    embed.add_field(name="Payment Intent ID", value=payment_intent_id, inline=False)
                if image_url:
                    embed.set_image(url=image_url)

                await admin_channel.send(embed=embed)
                logger.info(f"Notified admins about payment confirmation for user {ctx.author.id}")
            except discord.errors.Forbidden:
                logger.error(
                    f"Bot lacks permissions to send messages in the admin channel (ID: {admin_channel_id})"
                )
        else:
            logger.error(f"Admin notification channel not found. Searched for channel ID: {admin_channel_id}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """
        Handle messages in ticket channels and detect ticket creation requests.

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
                    await self.check_payment(ctx)
            elif message.content.lower() in {'payment verification', 'verify payment'}:
                await self.create_ticket(ctx, str(message.author.id))
                return

        await self.bot.process_commands(message)
