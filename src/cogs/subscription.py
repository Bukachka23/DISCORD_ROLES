import asyncio
import logging.config
from datetime import datetime, timedelta

import discord
from discord.ext import commands

from src.config.logger import LOGGING
from src.core.database import get_db
from src.core.models import User
from src.core.utils import get_customer_by_email, get_active_subscription, calculate_remaining_days

logging.config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)


class SubscriptionCog(commands.Cog):
    """Handles subscription-related commands."""

    def __init__(self, bot: commands.Bot, premium_role_id: int, admin_user_id: int):
        self.bot = bot
        self.premium_role_id = premium_role_id
        self.admin_user_id = admin_user_id
        logger.info("SubscriptionCog initialized")

    @commands.command(name='check_subscription')
    async def check_subscription(self, ctx: commands.Context) -> None:
        """
        Check the user's subscription status.

        Sends a DM to the user requesting their email to verify subscription details.
        """
        logger.info(f"Check subscription command invoked by user {ctx.author.id}")
        confirmation_message = await ctx.send("📬 I've sent you a DM with instructions. Please check your Direct "
                                              "Messages.")
        await confirmation_message.delete(delay=10)

        try:
            await ctx.author.send(
                "👋 **Hello!**\n\n"
                "To verify your subscription status, please provide the **email address** you used to purchase our "
                "premium plan.\n"
                "This will help us retrieve your subscription details accurately.\n\n"
                "🔍 *Example:* `user@example.com`"
            )
        except discord.Forbidden:
            logger.warning(f"Cannot send DM to user {ctx.author.id}. They might have DMs disabled.")
            await ctx.send(f"{ctx.author.mention}, I couldn't send you a DM. Please ensure your privacy settings "
                           f"allow DMs from server members.")

        def dm_check(message: discord.Message) -> bool:
            return message.author == ctx.author and isinstance(message.channel, discord.DMChannel)

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                email_message = await self.bot.wait_for('message', check=dm_check, timeout=120.0)
                email = email_message.content.strip()
                customer = get_customer_by_email(email)

                if not customer:
                    await ctx.author.send(
                        "❌ **No customer found** with that email address.\n"
                        "Please ensure you've entered the correct email associated with your premium purchase."
                    )
                    return

                subscription = get_active_subscription(customer)
                if not subscription:
                    await ctx.author.send(
                        "⚠️ **No active subscription** found for your account.\n"
                        "If you believe this is an error, please contact our support team for assistance."
                    )
                    return

                remaining_days = calculate_remaining_days(subscription)
                await ctx.author.send(
                    f"✅ **Subscription Active**\n\nYou have **{remaining_days} day(s)** remaining on your premium "
                    f"subscription. 🎉\n\n"
                    "If you wish to renew or modify your subscription, please use the appropriate commands."
                )
                logger.info(f"User {ctx.author.id} has {remaining_days} days left on subscription")
                break

            except asyncio.TimeoutError:
                if attempt < max_retries:
                    await ctx.author.send(
                        f"⏰ **Timeout**\n\nYou didn't respond within the allotted time. Please provide your email "
                        f"address to continue.\n"
                        f"You have **{max_retries - attempt} attempt(s)** remaining."
                    )
                else:
                    await ctx.author.send(
                        "⏰ **Session Timed Out**\n\nYou didn't respond in time. Please try the `!check_subscription` "
                        "command again when you're ready."
                    )
                    return

            except Exception as e:
                await ctx.author.send(
                    f"⚠️ **An error occurred** while processing your request. Please try again later or contact "
                    f"support.\n\n"
                    f"**Error Details:** {e!s}"
                )
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
        confirmation_message = await ctx.send("📬 I've sent you a DM with renewal instructions. Please check your "
                                              "Direct Messages.")
        await confirmation_message.delete(delay=10)

        try:
            await ctx.author.send(
                "🔄 **Renew Subscription**\n\n"
                "To renew your subscription, please provide the **email address** associated with your premium "
                "account.\n"
                "This will allow us to process your renewal accurately.\n\n"
                "🔍 *Example:* `user@example.com`"
            )
        except discord.Forbidden:
            logger.warning(f"Cannot send DM to user {ctx.author.id}. They might have DMs disabled.")
            await ctx.send(f"{ctx.author.mention}, I couldn't send you a DM. Please ensure your privacy settings "
                           f"allow DMs from server members.")

        def dm_check(message: discord.Message) -> bool:
            return message.author == ctx.author and isinstance(message.channel, discord.DMChannel)

        try:
            email_message = await self.bot.wait_for('message', check=dm_check, timeout=120.0)
            email = email_message.content.strip()
            customer = get_customer_by_email(email)

            if not customer:
                await ctx.author.send(
                    "❌ **No customer found** with that email address.\n"
                    "Please ensure you've entered the correct email associated with your premium purchase."
                )
                return

            subscription = get_active_subscription(customer)
            if not subscription:
                await ctx.author.send(
                    "⚠️ **No active subscription** found for your account.\n"
                    "If you wish to start a new subscription, please use the `!start_payment` command."
                )
                return

            remaining_days = calculate_remaining_days(subscription)
            new_end_date = datetime.utcnow() + timedelta(days=days + remaining_days)
            db = next(get_db())
            user = db.query(User).filter(User.discord_id == str(ctx.author.id)).first()
            if user:
                user.subscription_end = new_end_date
                db.commit()
                await ctx.author.send(
                    f"✅ **Subscription Renewed**\n\nYour subscription has been successfully renewed for **{days} day("
                    f"s)**.\n"
                    f"**New End Date:** {new_end_date.strftime('%Y-%m-%d')} 📅\n\n"
                    "Thank you for continuing your support!"
                )
                logger.info(f"Subscription successfully renewed for user {ctx.author.id}. New end date: {new_end_date}")
            else:
                await ctx.author.send(
                    "⚠️ **User Not Found**\n\nWe couldn't locate your account in our database. Please contact support "
                    "for assistance."
                )
                logger.warning(f"User {ctx.author.id} not found in database during renewal.")

        except asyncio.TimeoutError:
            await ctx.author.send(
                "⏰ **Session Timed Out**\n\nYou didn't respond in time. Please try the `!renew_subscription` command "
                "again when you're ready."
            )
            return

        except Exception as e:
            await ctx.author.send(
                f"⚠️ **An error occurred** while processing your renewal. "
                f"Please try again later or contact support.\n\n"
                f"**Error Details:** {e!s}"
            )
            logger.error(f"Error in renew_subscription for user {ctx.author.id}: {e!s}", exc_info=True)
