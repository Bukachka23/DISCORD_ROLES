import os
from datetime import datetime

import discord
import stripe
from aiohttp import web
from discord.ext import commands
from dotenv import load_dotenv

from bot.constants import EnvVariables, TicketState, ticket_info, ticket_states
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

        ticket_channel = await guild.create_text_channel(
            f'ticket-{user_id}',
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
        logger.error(f"Error creating ticket: {str(e)}")
        await ctx.send("An error occurred while creating the ticket. Please try again later.")
    finally:
        db.close()


async def process_ticket_info(message: discord.Message):
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
                f'Please share your payment confirmation here by attaching an image and including the PaymentIntent '
                f'ID in your message.'
            )
        else:
            await channel.send("Unexpected message. Please wait for further instructions.")

    except ValueError as e:
        await channel.send(f"Invalid input: {str(e)}. Please try again.")
    except Exception as e:
        logger.error(f"Error in ticket information process: {str(e)}")
        await channel.send("An error occurred during ticket information collection. Please try again later.")
        del ticket_states[author.id]
        if author.id in ticket_info:
            del ticket_info[author.id]


async def check_payment(ctx):
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
        await confirm_payment(ctx, user, db, payment_intent_id, image_url)

    except Exception as e:
        logger.error(f"Error checking payment: {str(e)}")
        await ctx.send('An error occurred while checking the payment. Please try again later.')
    finally:
        db.close()


async def confirm_payment(ctx, user, db, payment_intent_id, image_url):
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
        except discord.errors.Forbidden:
            logger.error(f"Bot doesn't have permission to assign roles for user {ctx.author}")
            await ctx.send("Error: Bot doesn't have permission to assign roles. Please contact an admin.")
        except Exception as e:
            logger.error(f"Error assigning PREMIUM role to {ctx.author}: {str(e)}")
            await ctx.send("An error occurred while assigning the PREMIUM role. Please contact an admin.")
    else:
        await ctx.send('Error: PREMIUM role not found. Please contact an admin.')
        logger.error(f"PREMIUM role not found. Searched for role ID: {premium_role_id}")
        logger.error(f"Available roles: {[role.name for role in ctx.guild.roles]}")

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


@bot.event
async def on_message(message: discord.Message) -> None:
    """Handle messages in ticket channels and detect ticket creation requests."""
    if message.author == bot.user:
        return

    if isinstance(message.channel, discord.TextChannel):
        if message.channel.name.startswith('ticket-'):
            if not message.content.startswith(bot.command_prefix):
                logger.info(f"Processing message in ticket channel: {message.content}")
                db = next(get_db())
                try:
                    user = db.query(User).filter(User.discord_id == str(message.author.id)).first()
                    premium_role_id = int(os.getenv(EnvVariables.PREMIUM_ROLE_ID.value))
                    premium_role = message.guild.get_role(premium_role_id)

                    if user:
                        if premium_role in message.author.roles:
                            await message.channel.send(
                                f'{message.author.mention}, you already have the PREMIUM role. No need to send payment '
                                f'confirmation again.')
                            logger.info(f"User {message.author} already has the PREMIUM role.")
                            return

                        existing_payment = db.query(Payment).filter(Payment.user_id == user.id,
                                                                    Payment.confirmed).first()
                        if existing_payment:
                            await message.channel.send(
                                f'{message.author.mention}, your payment has already been confirmed. No need to send '
                                f'confirmation again.')
                            logger.info(f"User {message.author}'s payment has already been confirmed.")
                            return

                    words = message.content.split()
                    payment_intent_id = next((word for word in words if word.startswith('pi_')), None)

                    if payment_intent_id or message.attachments:
                        logger.info(f"Calling check_payment for user {message.author}")
                        await check_payment(await bot.get_context(message))
                    else:
                        await process_ticket_info(message)

                except Exception as e:
                    logger.error(f"Error processing payment: {str(e)}")
                    await message.channel.send('An error occurred while processing the payment. Please contact an '
                                               'admin.')
                finally:
                    db.close()
        elif message.content.lower() in ['payment verification', 'verify payment']:
            ctx = await bot.get_context(message)
            await create_ticket(ctx, str(message.author.id))
            return

    await bot.process_commands(message)


if __name__ == '__main__':
    load_dotenv()
    PREMIUM_ROLE_ID = os.getenv('PREMIUM_ROLE_ID')
    stripe.api_key = os.getenv(EnvVariables.STRIPE_SECRET_KEY.value)

    init_db()
    bot.run(os.getenv("DISCORD_TOKEN"))
