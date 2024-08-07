import os
from datetime import datetime

import discord
from aiohttp import web
from discord.ext import commands
from dotenv import load_dotenv

from bot.constants import EnvVariables
from core.database import get_db, init_db
from core.models import Payment, Ticket, User
from image_processing.img_analyze import analyze_image, get_base64_image
from log.logger import logger

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='@', intents=intents)


async def start_http_server() -> None:
    """Start the HTTP server for health checks."""
    app = web.Application()
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 80)
    await site.start()


async def health_check(_) -> web.Response:
    """Health check endpoint for the HTTP server."""
    return web.json_response({'status': 'ok'})



@bot.event
async def on_ready() -> None:
    """Log the bot's connection to Discord."""
    logger.info(f'{bot.user} has connected to Discord!')

    for guild in bot.guilds:
        logger.info(f"Guild: {guild.name} (ID: {guild.id})")
        for role in guild.roles:
            logger.info(f"Role: {role.name} (ID: {role.id})")


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

        existing_ticket = db.query(Ticket).filter(Ticket.user_id == user.id, Ticket.closed_at is None).first()
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

        existing_ticket = db.query(Ticket).filter(Ticket.user_id == user.id, Ticket.closed_at is None).first()
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


@bot.event
async def on_message(message: discord.Message) -> None:
    """Analyze the image for payment confirmation."""
    if message.author == bot.user:
        return

    if isinstance(message.channel, discord.TextChannel) and message.channel.name.startswith('ticket-'):
        if message.attachments:
            db = next(get_db())
            try:
                user = db.query(User).filter(User.discord_id == str(message.author.id)).first()
                premium_role = message.guild.get_role(PREMIUM_ROLE_ID)

                if user:
                    if premium_role in message.author.roles:
                        await message.channel.send(
                            f'{message.author.mention}, you already have the PREMIUM role. No need to send the image '
                            f'again.')
                        logger.info(f"User {message.author} already has the PREMIUM role.")
                        return

                    existing_payment = db.query(Payment).filter(Payment.user_id == user.id,
                                                                Payment.confirmed).first()
                    if existing_payment:
                        await message.channel.send(
                            f'{message.author.mention}, your payment has already been confirmed. No need to send the '
                            f'image again.')
                        logger.info(f"User {message.author}'s payment has already been confirmed.")
                        return

                for attachment in message.attachments:
                    if attachment.content_type.startswith('image/'):
                        base64_image = await get_base64_image(attachment)
                        is_payment_successful = await analyze_image(message, base64_image)
                        if is_payment_successful:
                            if user:
                                user.premium = True
                                payment = Payment(
                                    user_id=user.id,
                                    confirmed=True,
                                    confirmation_image=attachment.url,
                                    created_at=datetime.utcnow()
                                )
                                db.add(payment)
                                db.commit()
                            if premium_role:
                                await message.author.add_roles(premium_role)
                                await message.channel.send(
                                    f'Payment confirmed! {message.author.mention} has been granted the PREMIUM role.')
                                logger.info(f"Granted PREMIUM role to {message.author}")
                            else:
                                await message.channel.send('Error: PREMIUM role not found. Please contact an admin.')
                                logger.error(f"PREMIUM role not found. Searched for role ID: {PREMIUM_ROLE_ID}")
                        else:
                            await message.channel.send(
                                'Payment confirmation not detected. Please try again with a clear image of your '
                                'payment confirmation.')
                            logger.warning("Payment confirmation not detected")
                        break
            except Exception as e:
                logger.error(f"Error processing payment: {str(e)}")
                await message.channel.send('An error occurred while processing the payment. Please contact an admin.')
            finally:
                db.close()

    await bot.process_commands(message)


if __name__ == '__main__':
    load_dotenv()
    PREMIUM_ROLE_ID = int(os.getenv(EnvVariables.PREMIUM_ROLE_ID.value))

    init_db()
    bot.run(os.getenv("DISCORD_TOKEN"))
