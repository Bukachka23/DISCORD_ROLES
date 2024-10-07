import asyncio
import logging.config
from datetime import datetime, timedelta
from typing import Optional

import discord
from discord.ext import commands

from src.config.logger import LOGGING
from src.config.settings import ConfigConstants
from src.core.database import get_db
from src.core.models import User
from src.core.utils import (
    get_customer_by_email,
    get_active_subscription,
    calculate_remaining_days,
)

logging.config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)


class SubscriptionCog(commands.Cog):
    """Handles subscription-related commands."""

    def __init__(
        self, bot: commands.Bot, premium_role_id: int, admin_user_id: int
    ):
        self.bot = bot
        self.premium_role_id = premium_role_id
        self.admin_user_id = admin_user_id
        logger.info("SubscriptionCog initialized")

    async def send_dm(
        self, user: discord.User, content: str
    ) -> Optional[discord.Message]:
        """Send a direct message to the user.

        Args:
            user (discord.User): The user to send the DM to.
            content (str): The content of the DM.

        Returns:
            Optional[discord.Message]: The sent message, or None if failed.
        """
        try:
            message = await user.send(content)
            return message
        except discord.Forbidden:
            logger.warning(
                f"Cannot send DM to user {user.id}. They might have DMs disabled."
            )
            await self.bot.get_channel(user.id).send(
                f"{user.mention}, I couldn't send you a DM. "
                f"Please ensure your privacy settings allow DMs from server members."
            )
            return None

    async def get_user_email(
        self, ctx: commands.Context
    ) -> Optional[str]:
        """Prompt the user for their email and retrieve it.

        Args:
            ctx (commands.Context): The context of the command.

        Returns:
            Optional[str]: The user's email if provided, else None.
        """
        def check(message: discord.Message) -> bool:
            return (
                message.author == ctx.author
                and isinstance(message.channel, discord.DMChannel)
            )

        for attempt in range(1, ConfigConstants.MAX_RETRIES + 1):
            try:
                email_message = await self.bot.wait_for(
                    "message", check=check, timeout=ConfigConstants.RESPONSE_TIMEOUT
                )
                email = email_message.content.strip()
                return email
            except asyncio.TimeoutError:
                if attempt < ConfigConstants.MAX_RETRIES:
                    await self.send_dm(
                        ctx.author,
                        (
                            f"⏰ **Timeout**\n\nYou didn't respond within the allotted time. "
                            f"Please provide your email address to continue.\n"
                            f"You have **{ConfigConstants.MAX_RETRIES - attempt} attempt(s)** remaining."
                        ),
                    )
                else:
                    await self.send_dm(
                        ctx.author,
                        (
                            "⏰ **Session Timed Out**\n\nYou didn't respond in time. "
                            "Please try the command again when you're ready."
                        ),
                    )
                    return None

    async def process_subscription(
        self, ctx: commands.Context, email: str
    ) -> Optional[int]:
        """Process the user's subscription based on the provided email.

        Args:
            ctx (commands.Context): The context of the command.
            email (str): The user's email address.

        Returns:
            Optional[int]: Remaining subscription days if active, else None.
        """
        customer = get_customer_by_email(email)
        if not customer:
            await self.send_dm(
                ctx.author,
                (
                    "❌ **No customer found** with that email address.\n"
                    "Please ensure you've entered the correct email associated with your premium purchase."
                ),
            )
            return None

        subscription = get_active_subscription(customer)
        if not subscription:
            await self.send_dm(
                ctx.author,
                (
                    "⚠️ **No active subscription** found for your account.\n"
                    "If you believe this is an error, please contact our support team for assistance."
                ),
            )
            return None

        remaining_days = calculate_remaining_days(subscription)
        await self.send_dm(
            ctx.author,
            (
                f"✅ **Subscription Active**\n\nYou have **{remaining_days} day(s)** remaining on your premium "
                f"subscription. 🎉\n\n"
                "If you wish to renew or modify your subscription, please use the appropriate commands."
            ),
        )
        logger.info(
            f"User {ctx.author.id} has {remaining_days} day(s) left on subscription."
        )
        return remaining_days

    async def process_renewal(
        self, ctx: commands.Context, email: str, days: int
    ) -> bool:
        """Process the renewal of the user's subscription.

        Args:
            ctx (commands.Context): The context of the command.
            email (str): The user's email address.
            days (int): Number of days to extend the subscription.

        Returns:
            bool: True if renewal was successful, False otherwise.
        """
        customer = get_customer_by_email(email)
        if not customer:
            await self.send_dm(
                ctx.author,
                (
                    "❌ **No customer found** with that email address.\n"
                    "Please ensure you've entered the correct email associated with your premium purchase."
                ),
            )
            return False

        subscription = get_active_subscription(customer)
        if not subscription:
            await self.send_dm(
                ctx.author,
                (
                    "⚠️ **No active subscription** found for your account.\n"
                    "If you wish to start a new subscription, please use the !start_payment command."
                ),
            )
            return False

        remaining_days = calculate_remaining_days(subscription)
        new_end_date = datetime.utcnow() + timedelta(days=days + remaining_days)

        try:
            async with get_db() as db:
                user = (
                    await db.query(User)
                    .filter(User.discord_id == str(ctx.author.id))
                    .first()
                )
                if user:
                    user.subscription_end = new_end_date
                    await db.commit()
                else:
                    await self.send_dm(
                        ctx.author,
                        (
                            "⚠️ **User Not Found**\n\nWe couldn't locate your account in our database. "
                            "Please contact support for assistance."
                        ),
                    )
                    logger.warning(
                        f"User {ctx.author.id} not found in database during renewal."
                    )
                    return False
        except Exception as e:
            await self.send_dm(
                ctx.author,
                (
                    f"⚠️ **An error occurred** while processing your renewal. "
                    f"Please try again later or contact support.\n\n"
                    f"**Error Details:** {e!s}"
                ),
            )
            logger.error(
                f"Error in renew_subscription for user {ctx.author.id}: {e!s}",
                exc_info=True,
            )
            return False

        await self.send_dm(
            ctx.author,
            (
                f"✅ **Subscription Renewed**\n\nYour subscription "
                f"has been successfully renewed for **{days} day(s)**.\n"
                f"**New End Date:** {new_end_date.strftime('%Y-%m-%d')} 📅\n\n"
                "Thank you for continuing your support!"
            ),
        )
        logger.info(
            f"Subscription successfully renewed for user {ctx.author.id}. New end date: {new_end_date}"
        )
        return True

    @commands.command(name="check_subscription")
    async def check_subscription(self, ctx: commands.Context) -> None:
        """
        Check the user's subscription status.

        Sends a DM to the user requesting their email to verify subscription details.
        """
        logger.info(f"Check subscription command invoked by user {ctx.author.id}")
        confirmation_message = await ctx.send(
            "📬 I've sent you a DM with instructions. Please check your Direct Messages."
        )
        await confirmation_message.delete(delay=ConfigConstants.CONFIRM_DELETE_DELAY)

        dm_content = (
            "👋 **Hello!**\n\n"
            "To verify your subscription status, please provide the **email address** you used to purchase our "
            "premium plan.\n"
            "This will help us retrieve your subscription details accurately.\n\n"
            "🔍 *Example:* user@example.com"
        )
        dm_sent = await self.send_dm(ctx.author, dm_content)
        if not dm_sent:
            return

        try:
            email = await self.get_user_email(ctx)
            if not email:
                return

            await self.process_subscription(ctx, email)

        except Exception as e:
            await self.send_dm(
                ctx.author,
                (
                    f"⚠️ **An error occurred** while processing your request. Please try again later or contact "
                    f"support.\n\n"
                    f"**Error Details:** {e!s}"
                ),
            )
            logger.error(
                f"Error in check_subscription for user {ctx.author.id} ({ctx.author}): {e!s}",
                exc_info=True,
            )

    @commands.command(name="renew_subscription")
    async def renew_subscription(
        self, ctx: commands.Context, days: int
    ) -> None:
        """
        Renew the user's subscription for a specified number of days.

        Args:
            days (int): Number of days to extend the subscription.
            :param days: Number of days to extend the subscription.
            :param ctx: The context of the command.
        """
        logger.info(
            f"Renew subscription command invoked by user {ctx.author.id} for {days} day(s)"
        )
        confirmation_message = await ctx.send(
            "📬 I've sent you a DM with renewal instructions. Please check your Direct Messages."
        )
        await confirmation_message.delete(delay=ConfigConstants.CONFIRM_DELETE_DELAY)

        dm_content = (
            "🔄 **Renew Subscription**\n\n"
            "To renew your subscription, please provide the **email address** associated with your premium "
            "account.\n"
            "This will allow us to process your renewal accurately.\n\n"
            "🔍 *Example:* user@example.com"
        )
        dm_sent = await self.send_dm(ctx.author, dm_content)
        if not dm_sent:
            return

        try:
            email = await self.get_user_email(ctx)
            if not email:
                return

            success = await self.process_renewal(ctx, email, days)
            if not success:
                return

        except Exception as e:
            await self.send_dm(
                ctx.author,
                (
                    f"⚠️ **An error occurred** while processing your renewal. "
                    f"Please try again later or contact support.\n\n"
                    f"**Error Details:** {e!s}"
                ),
            )
            logger.error(
                f"Error in renew_subscription for user {ctx.author.id}: {e!s}",
                exc_info=True,
            )
