import asyncio
import logging.config
from datetime import datetime
from sqlalchemy.future import select
from typing import Optional

import discord
import stripe
from discord.ext import commands

from sqlalchemy.ext.asyncio import AsyncSession

from src.config.logger import LOGGING
from src.config.settings import (
    ConfigConstants,
    get_welcome_message,
)
from src.core.database import get_db
from src.core.models import Payment, User
from src.core.utils import verify_payment_intent

logging.config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)


class PaymentCog(commands.Cog):
    """Handles payment verification and related processes."""

    def __init__(
        self, bot: commands.Bot, premium_role_id: int, admin_user_id: int
    ):
        self.bot = bot
        self.premium_role_id = premium_role_id
        self.admin_user_id = admin_user_id
        logger.info("PaymentCog initialized")

    @commands.command(name="check_payment")
    async def check_payment(self, ctx: commands.Context) -> None:
        """Check payment for the user."""
        logger.info(f"Checking payment for user {ctx.author.id}")
        confirmation_message = await ctx.send(
            "📬 I've received your payment details. Processing your payment..."
        )
        await confirmation_message.delete(delay=ConfigConstants.CONFIRM_DELETE_DELAY)

        async with get_db() as db:
            try:
                user = await self.get_user(db, str(ctx.author.id))
                if not user:
                    await ctx.send(f"{ctx.author.mention}, you do not have any tickets.")
                    return

                payment_intent_id = self.extract_payment_intent_id(
                    ctx.message.content
                )
                if not payment_intent_id:
                    await ctx.send(
                        "❌ **Missing PaymentIntent ID**\n\n"
                        "Please provide a valid PaymentIntent ID starting with pi_ along with the image.\n\n"
                        "*Example:* pi_1Hh1XYZAbCdEfGhIjKlMnOpQ"
                    )
                    return

                attachment = await self.get_valid_attachment(ctx)
                if not attachment:
                    return

                image_url = attachment.url

                logger.info(
                    f"Calling confirm_payment for user {ctx.author.id}"
                )
                await self.confirm_payment(
                    ctx, user, db, payment_intent_id, image_url
                )

            except Exception as e:
                logger.error(
                    f"Error checking payment for user {ctx.author.id}: {e!s}",
                    exc_info=True,
                )
                await ctx.send(
                    "⚠️ **An error occurred** while checking your payment. "
                    "Please try again later or contact support for assistance."
                )

    async def get_user(
            self, db: AsyncSession, discord_id: str
    ) -> Optional[User]:
        """
        Retrieve the user from the database based on Discord ID.

        Args:
            db (AsyncSession): The database session.
            discord_id (int): The Discord user ID.

        Returns:
            Optional[User]: The user object if found, else None.
        """
        result = await db.execute(
            select(User).where(User.discord_id == discord_id)
        )
        user = result.scalar_one_or_none()
        return user

    def extract_payment_intent_id(
        self, message_content: str
    ) -> Optional[str]:
        """
        Extract the PaymentIntent ID from the message content.

        Args:
            message_content (str): The content of the message.

        Returns:
            Optional[str]: The PaymentIntent ID if found, else None.
        """
        words = message_content.split()
        payment_intent_id = next(
            (
                word
                for word in words
                if word.startswith(ConfigConstants.PAYMENT_INTENT_PREFIX)
            ),
            None,
        )
        return payment_intent_id

    async def get_valid_attachment(
        self, ctx: commands.Context
    ) -> Optional[discord.Attachment]:
        """
        Validate and retrieve the attachment from the message.

        Args:
            ctx (commands.Context): The context of the command.

        Returns:
            Optional[discord.Attachment]: The valid attachment if present, else None.
        """
        if not ctx.message.attachments:
            await ctx.send(
                "❌ **Missing Attachment**\n\n"
                "Please attach an image of your payment confirmation along with the PaymentIntent ID."
            )
            return None

        attachment = ctx.message.attachments[0]
        if not attachment.filename.lower().endswith(
            ConfigConstants.VALID_ATTACHMENT_EXTENSIONS
        ):
            await ctx.send(
                "❌ **Invalid Attachment Format**\n\n"
                "Please attach a valid image file in one of the following formats: PNG, JPG, JPEG, WEBP, GIF."
            )
            return None

        return attachment

    async def confirm_payment(
        self,
        ctx: commands.Context,
        user: User,
        db: AsyncSession,
        payment_intent_id: str,
        image_url: str,
    ) -> None:
        """
        Confirm the payment and assign the PREMIUM role to the user.

        Args:
            ctx (commands.Context): The context of the command.
            user (User): The user object from the database.
            db (AsyncSession): The database session.
            payment_intent_id (str): The Stripe PaymentIntent ID.
            image_url (str): URL of the payment confirmation image.
        """
        try:
            payment_intent = await self.verify_payment(payment_intent_id)
            if not payment_intent:
                await ctx.send(
                    "❌ **Payment Verification Failed**\n\n"
                    "We couldn't verify your payment. Please ensure you've provided the correct PaymentIntent ID and "
                    "a valid payment confirmation image.\n"
                    "If the issue persists, please contact support for assistance."
                )
                return

            order_id = payment_intent.metadata.get('order_id')
            if not order_id:
                await ctx.send(
                    "❌ **Order ID Missing**\n\n"
                    "The PaymentIntent does not have an associated Order ID. Please contact support for assistance."
                )
                return

            result = await db.execute(
                select(Payment).filter(Payment.order_id == order_id)
            )
            existing_payment = result.scalar_one_or_none()
            if existing_payment:
                await ctx.send(
                    "❌ **Order ID Invalid**\n\n"
                    "This Order ID has already been used. Please provide a valid Order ID."
                )
                return

            user.premium = True

            payment = Payment(
                user_id=user.id,
                payment_intent_id=payment_intent_id,
                order_id=order_id,
                confirmation_image=image_url,
                confirmed=True,
                created_at=datetime.utcnow(),
            )
            db.add(payment)
            await db.commit()

            premium_role = ctx.guild.get_role(self.premium_role_id)
            if not premium_role:
                await ctx.send(
                    "⚠️ **Role Not Found**\n\n"
                    "The PREMIUM role does not exist on this server. Please contact an admin to resolve this issue."
                )
                logger.error(
                    f"PREMIUM role not found. Searched for role ID: {self.premium_role_id}"
                )
                return

            try:
                await ctx.author.add_roles(premium_role)
                await ctx.send(
                    f"🎉 **Payment Confirmed!**\n\n"
                    f"{ctx.author.mention}, you have been granted the **PREMIUM** role. Enjoy your premium benefits! 🎊"
                )
                logger.info(
                    f"Granted PREMIUM role (ID: {self.premium_role_id}) to {ctx.author.id}"
                )

                await self.send_welcome_message(ctx)
            except discord.errors.Forbidden:
                logger.error(
                    f"Bot lacks permissions to assign roles to user {ctx.author.id}"
                )
                await ctx.send(
                    "⚠️ **Permission Error**\n\n"
                    "I don't have the necessary permissions to assign roles. Please contact an admin for assistance."
                )
            except Exception as e:
                logger.error(
                    f"Error assigning PREMIUM role to {ctx.author.id}: {e}",
                    exc_info=True,
                )
                await ctx.send(
                    "⚠️ **Assignment Error**\n\n"
                    "An error occurred while assigning the PREMIUM role. Please contact an admin for assistance."
                )

            await self.notify_admins(ctx, user, payment_intent_id, image_url)

        except Exception as e:
            logger.error(
                f"Error in confirm_payment for user {ctx.author.id}: {e}",
                exc_info=True,
            )
            await ctx.send(
                "⚠️ **An error occurred** while confirming your payment. "
                "Please try again later or contact support for assistance."
            )

    async def verify_payment(
        self, payment_intent_id: str
    ) -> Optional[stripe.PaymentIntent]:
        """
        Verify the PaymentIntent ID asynchronously.

        Args:
            payment_intent_id (str): The Stripe PaymentIntent ID.

        Returns:
            Optional[stripe.PaymentIntent]: The PaymentIntent object if verified, else None.
        """
        loop = asyncio.get_event_loop()
        payment_intent = await loop.run_in_executor(
            None, verify_payment_intent, payment_intent_id
        )
        return payment_intent

    @staticmethod
    async def send_welcome_message(
        ctx: commands.Context, days: int = 30
    ) -> None:
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
        admin_channel = await self.get_admin_channel(ctx.guild)

        if not admin_channel:
            logger.error(
                f"Admin notification channel not found. Searched for channel ID: "
                f"{ConfigConstants.ADMIN_CHANNEL_ID}"
            )
            return

        try:
            embed = discord.Embed(
                title="🆕 New Payment Confirmation",
                description=f"**User:** {ctx.author.mention}\n**User ID:** {user.id}",
                color=discord.Color.green(),
                timestamp=datetime.utcnow(),
            )
            if payment_intent_id:
                embed.add_field(
                    name="💳 Payment Intent ID",
                    value=payment_intent_id,
                    inline=False,
                )
            if image_url:
                embed.set_image(url=image_url)
            embed.set_footer(text="Payment Verification")

            await admin_channel.send(embed=embed)
            logger.info(
                f"Notified admins about payment confirmation for user {ctx.author.id}"
            )
        except discord.errors.Forbidden:
            logger.error(
                f"Bot lacks permissions to send messages in the admin channel (ID: {ConfigConstants.ADMIN_CHANNEL_ID})"
            )
        except Exception as e:
            logger.error(
                f"Error notifying admins in channel {ConfigConstants.ADMIN_CHANNEL_ID}: {e!s}",
                exc_info=True,
            )

    async def get_admin_channel(
        self, current_guild: discord.Guild
    ) -> Optional[discord.TextChannel]:
        """
        Retrieve the admin channel from the current guild or other guilds.

        Args:
            current_guild (discord.Guild): The guild where the command was invoked.

        Returns:
            Optional[discord.TextChannel]: The admin channel if found, else None.
        """
        admin_channel = current_guild.get_channel(
            ConfigConstants.ADMIN_CHANNEL_ID
        )
        if admin_channel:
            return admin_channel

        for guild in self.bot.guilds:
            admin_channel = guild.get_channel(ConfigConstants.ADMIN_CHANNEL_ID)
            if admin_channel:
                return admin_channel

        return None
