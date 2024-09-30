import logging.config
from datetime import datetime
from typing import Any

import discord
from discord.ext import commands

from src.config.logger import LOGGING
from src.config.settings import EnvSettings, get_welcome_message
from src.core.database import get_db
from src.core.models import Payment, User
from src.core.utils import verify_payment_intent

logging.config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)


class PaymentCog(commands.Cog):
    """Handles payment verification and related processes."""

    def __init__(self, bot: commands.Bot, premium_role_id: int, admin_user_id: int):
        self.bot = bot
        self.premium_role_id = premium_role_id
        self.admin_user_id = admin_user_id
        logger.info("PaymentCog initialized")

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
                await ctx.send(f"{ctx.author.mention}, you do not have any tickets.")
                return

            words = ctx.message.content.split()
            payment_intent_id = next((word for word in words if word.startswith('pi_')), None)

            if not ctx.message.attachments:
                await ctx.send(
                    "❌ **Missing Attachment**\n\n"
                    "Please attach an image of your payment confirmation along with the PaymentIntent ID."
                )
                return

            attachment = ctx.message.attachments[0]
            if not attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                await ctx.send(
                    "❌ **Invalid Attachment Format**\n\n"
                    "Please attach a valid image file in one of the following formats: `PNG`, `JPG`, `JPEG`, `WEBP`, "
                    "`GIF`."
                )
                return

            image_url = attachment.url

            if not payment_intent_id:
                await ctx.send(
                    "❌ **Missing PaymentIntent ID**\n\n"
                    "Please provide a valid PaymentIntent ID starting with `pi_` along with the image.\n\n"
                    "*Example:* `pi_1Hh1XYZAbCdEfGhIjKlMnOpQ`"
                )
                return

            logger.info(f"Calling confirm_payment for user {ctx.author.id}")
            await self.confirm_payment(ctx, user, db, payment_intent_id, image_url)

        except Exception as e:
            logger.error(f"Error checking payment for user {ctx.author.id}: {e!s}", exc_info=True)
            await ctx.send(
                "⚠️ **An error occurred** while checking your payment. Please try again later or contact support for "
                "assistance."
            )

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
            payment_verified = verify_payment_intent(payment_intent_id)

            if not payment_verified:
                await ctx.send(
                    "❌ **Payment Verification Failed**\n\n"
                    "We couldn't verify your payment. Please ensure you've provided the correct PaymentIntent ID and "
                    "a valid payment confirmation image.\n"
                    "If the issue persists, please contact support for assistance."
                )
                return

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

            premium_role = ctx.guild.get_role(self.premium_role_id)

            if premium_role:
                try:
                    await ctx.author.add_roles(premium_role)
                    await ctx.send(
                        f"🎉 **Payment Confirmed!**\n\n"
                        f"{ctx.author.mention}, you have been granted the **PREMIUM** role. Enjoy your premium "
                        f"benefits! 🎊"
                    )
                    logger.info(f"Granted PREMIUM role (ID: {self.premium_role_id}) to {ctx.author.id}")

                    await self.send_welcome_message(ctx)
                except discord.errors.Forbidden:
                    logger.error(f"Bot lacks permissions to assign roles to user {ctx.author.id}")
                    await ctx.send(
                        "⚠️ **Permission Error**\n\n"
                        "I don't have the necessary permissions to assign roles. Please contact an admin for "
                        "assistance."
                    )
                except Exception as e:
                    logger.error(f"Error assigning PREMIUM role to {ctx.author.id}: {e!s}", exc_info=True)
                    await ctx.send(
                        "⚠️ **Assignment Error**\n\n"
                        "An error occurred while assigning the PREMIUM role. Please contact an admin for assistance."
                    )
            else:
                await ctx.send(
                    "⚠️ **Role Not Found**\n\n"
                    "The PREMIUM role does not exist on this server. Please contact an admin to resolve this issue."
                )
                logger.error(f"PREMIUM role not found. Searched for role ID: {self.premium_role_id}")

            await self.notify_admins(ctx, user, payment_intent_id, image_url)

        except Exception as e:
            logger.error(f"Error in confirm_payment for user {ctx.author.id}: {e!s}", exc_info=True)
            await ctx.send(
                "⚠️ **An error occurred** while confirming your payment. Please try again later or contact support "
                "for assistance."
            )

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
        admin_channel_id = EnvSettings.ADMIN_USER_ID
        admin_channel = ctx.guild.get_channel(admin_channel_id)

        if not admin_channel:
            for guild in self.bot.guilds:
                admin_channel = guild.get_channel(admin_channel_id)
                if admin_channel:
                    break

        if admin_channel:
            try:
                embed = discord.Embed(
                    title="🆕 New Payment Confirmation",
                    description=f"**User:** {ctx.author.mention}\n**User ID:** {user.id}",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                if payment_intent_id:
                    embed.add_field(name="💳 Payment Intent ID", value=payment_intent_id, inline=False)
                if image_url:
                    embed.set_image(url=image_url)
                embed.set_footer(text="Payment Verification")

                await admin_channel.send(embed=embed)
                logger.info(f"Notified admins about payment confirmation for user {ctx.author.id}")
            except discord.errors.Forbidden:
                logger.error(
                    f"Bot lacks permissions to send messages in the admin channel (ID: {admin_channel_id})"
                )
            except Exception as e:
                logger.error(f"Error notifying admins in channel {admin_channel_id}: {e!s}", exc_info=True)
        else:
            logger.error(f"Admin notification channel not found. Searched for channel ID: {admin_channel_id}")
