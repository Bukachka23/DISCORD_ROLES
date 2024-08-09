import os
from datetime import datetime

import discord
import stripe
from aiohttp import web
from discord.ext import commands
from dotenv import load_dotenv

from bot.constants import EnvVariables
from core.database import get_db, init_db
from core.helpers import create_payment_intent
from core.models import Payment, Ticket, User
from log.logger import logger

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True
intents.members = True
intents.reactions = True
intents.typing = False
intents.presences = False
bot = commands.Bot(command_prefix='@', intents=intents)


async def start_http_server():
    """Start the HTTP server for health checks."""
    app = web.Application()
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    logger.info("HTTP server started for health checks on port 80")


async def health_check(_) -> web.Response:
    """Health check endpoint for the HTTP server."""
    logger.info("Health check requested")
    try:
        db = next(get_db())
        db.execute("SELECT 1")
        db.close()
        logger.info("Database connection successful")
        return web.json_response({'status': 'ok'})
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return web.json_response({'status': 'error', 'message': str(e)}, status=500)


@bot.event
async def on_ready():
    """Log the bot's connection to Discord and start the HTTP server."""
    logger.info(f'{bot.user} has connected to Discord!')

    for guild in bot.guilds:
        logger.info(f"Guild: {guild.name} (ID: {guild.id})")
        for role in guild.roles:
            logger.info(f"Role: {role.name} (ID: {role.id})")

    await start_http_server()
    logger.info("Bot is fully ready and HTTP server is started")


@bot.command(name='delete_ticket')
async def delete_ticket(ctx) -> None:
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
        logger.error(f"Error deleting ticket: {str(e)}")
        await ctx.send("An error occurred while deleting the ticket. Please try again later.")
    finally:
        db.close()


@bot.command(name='create_ticket')
async def create_ticket(ctx: commands.Context) -> None:
    """Create a ticket for the user."""
    guild = ctx.guild
    member = ctx.author

    db = next(get_db())
    try:
        user = db.query(User).filter(User.discord_id == str(member.id)).first()
        if not user:
            user = User(discord_id=str(member.id))
            db.add(user)
            db.commit()

        existing_ticket = db.query(Ticket).filter(Ticket.user_id == user.id, Ticket.closed_at.is_(None)).first()
        if existing_ticket:
            ticket_channel = guild.get_channel(int(existing_ticket.channel_id))
            if ticket_channel is None:
                existing_ticket.deleted_at = datetime.utcnow()
                db.commit()
            else:
                await ctx.send(f'{member.mention}, you already have an open ticket: <#{existing_ticket.channel_id}>')
                logger.info(f"User {member} already has an open ticket: <#{existing_ticket.channel_id}>")
                return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        ticket_channel = await guild.create_text_channel(
            f'ticket-{member.id}',
            overwrites=overwrites,
            category=discord.utils.get(guild.categories, name='TICKETS')
        )

        new_ticket = Ticket(channel_id=str(ticket_channel.id), user_id=user.id, created_at=datetime.utcnow())
        db.add(new_ticket)
        db.commit()

        await ticket_channel.send(
            f'{member.mention}, your ticket has been created. Please share your payment confirmation here.')
        await ctx.send(f'{member.mention}, your ticket has been created: {ticket_channel.mention}')
        logger.info(f"Created ticket channel {ticket_channel.name} for user {member}")
    except Exception as e:
        logger.error(f"Error creating ticket: {str(e)}")
        await ctx.send("An error occurred while creating the ticket. Please try again later.")
    finally:
        db.close()


@bot.command(name='create_payment')
async def create_payment(ctx, amount: int, currency: str, order_id: str) -> None:
    """
    Create a payment intent and return the PaymentIntent ID.
    Usage: @create_payment <amount_in_cents> <currency> <order_id>
    """
    logger.info(f"Create payment command invoked by {ctx.author}: "
                f"amount={amount}, "
                f"currency={currency}, "
                f"order_id={order_id}")
    try:
        payment_intent = create_payment_intent(amount, currency, order_id)
        await ctx.send(f"PaymentIntent created successfully. ID: {payment_intent.id}")
        logger.info(f"PaymentIntent created and sent to user: {payment_intent.id}")
    except stripe.error.StripeError as e:
        await ctx.send(f"An error occurred: {str(e)}")
        logger.error(f"Error in create_payment command: {str(e)}")


@bot.command(name='check_payment')
async def check_payment(ctx):
    """
    Check the payment and assign the PREMIUM role based on the provided PaymentIntent ID and image attachment.
    """
    if not ctx.message.content.startswith(bot.command_prefix):
        return

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

        await confirm_payment(ctx, user, db, payment_intent_id, image_url)

    except Exception as e:
        logger.error(f"Error checking payment: {str(e)}")
        await ctx.send('An error occurred while checking the payment. Please try again later.')
    finally:
        db.close()


async def confirm_payment(ctx, user, db, payment_intent_id, image_url):
    """
    Confirm the payment and grant the PREMIUM role.
    """
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

    premium_role = ctx.guild.get_role(PREMIUM_ROLE_ID)
    if premium_role:
        try:
            await ctx.author.add_roles(premium_role)
            await ctx.send(f'Payment confirmed! {ctx.author.mention} has been granted the PREMIUM role.')
            logger.info(f"Granted PREMIUM role to {ctx.author}")
        except discord.errors.Forbidden:
            logger.error(f"Bot doesn't have permission to assign roles for user {ctx.author}")
            await ctx.send("Error: Bot doesn't have permission to assign roles. Please contact an admin.")
        except Exception as e:
            logger.error(f"Error assigning PREMIUM role to {ctx.author}: {str(e)}")
            await ctx.send("An error occurred while assigning the PREMIUM role. Please contact an admin.")
    else:
        await ctx.send('Error: PREMIUM role not found. Please contact an admin.')
        logger.error(f"PREMIUM role not found. Searched for role ID: {PREMIUM_ROLE_ID}")

    await notify_admins(ctx, user, payment_intent_id, image_url)


async def notify_admins(ctx, user, payment_intent_id, image_url):
    """
    Notify admins about the new payment confirmation.
    """
    admin_channel_id = int(os.getenv(EnvVariables.ADMIN_USER_ID.value))

    admin_channel = ctx.guild.get_channel(admin_channel_id)

    if not admin_channel:
        for guild in bot.guilds:
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
            logger.error(f"Bot doesn't have permission to send messages in the admin channel (ID: {admin_channel_id})")
    else:
        logger.error(f"Admin notification channel not found. Searched for channel ID: {admin_channel_id}")


@bot.command(name='payment_help')
async def payment_help(ctx) -> None:
    """Provide instructions on how to use the check_payment command."""
    help_message = (
        "To check your payment status, use one of the following methods:\n\n"
        "1. Call the `@create_payment` command.\n"
        "2. Provide <amount in usd> <currency> <order_id>"
        "3. Copy the PaymentIntent ID and use the `@check_payment` command.\n"
        "4. Provide a PaymentIntent ID:\n"
        "`@check_payment <payment_intent_id>`\n"
        "Replace `<payment_intent_id>` with your PaymentIntent ID provided during the payment process.\n"
        "Example: `@check_payment pi_1234567890abcdef`\n\n"
        "5. Attach an image of your payment confirmation:\n"
        "Simply use the command `@check_payment` and attach an image to your message."
    )
    await ctx.send(help_message)


@bot.event
async def on_message(message: discord.Message) -> None:
    """Handle messages in ticket channels."""
    if message.author == bot.user:
        return

    if isinstance(message.channel, discord.TextChannel) and message.channel.name.startswith('ticket-'):
        if not message.content.startswith(bot.command_prefix):
            db = next(get_db())
            try:
                user = db.query(User).filter(User.discord_id == str(message.author.id)).first()
                premium_role = message.guild.get_role(EnvVariables.PREMIUM_ROLE_ID.value)

                if user:
                    if premium_role in message.author.roles:
                        await message.channel.send(
                            f'{message.author.mention}, you already have the PREMIUM role. No need to send payment '
                            f'confirmation again.')
                        logger.info(f"User {message.author} already has the PREMIUM role.")
                        return

                    existing_payment = db.query(Payment).filter(Payment.user_id == user.id, Payment.confirmed).first()
                    if existing_payment:
                        await message.channel.send(
                            f'{message.author.mention}, your payment has already been confirmed. No need to send '
                            f'confirmation again.')
                        logger.info(f"User {message.author}'s payment has already been confirmed.")
                        return

                words = message.content.split()
                payment_intent_id = next((word for word in words if word.startswith('pi_')), None)

                if payment_intent_id or message.attachments:
                    await check_payment(await bot.get_context(message), payment_intent_id)
                else:
                    await message.channel.send(
                        'Please provide a valid PaymentIntent ID starting with "pi_" or attach an image of your '
                        'payment confirmation.')

            except Exception as e:
                logger.error(f"Error processing payment: {str(e)}")
                await message.channel.send('An error occurred while processing the payment. Please contact an admin.')
            finally:
                db.close()

    await bot.process_commands(message)


if __name__ == '__main__':
    load_dotenv()
    PREMIUM_ROLE_ID = os.getenv(EnvVariables.PREMIUM_ROLE_ID.value)
    stripe.api_key = os.getenv(EnvVariables.STRIPE_SECRET_KEY.value)

    init_db()
    bot.run(os.getenv("DISCORD_TOKEN"))
