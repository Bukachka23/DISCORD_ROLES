import asyncio
import logging.config
import os

import discord
import stripe
from dotenv import load_dotenv

from src.core.constants import EnvVariables
from src.config.log_config import LOGGING
from src.core.database import init_db
from src.bot.discord_bot import DiscordBot

load_dotenv()

logging.config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)

TOKEN = os.getenv('DISCORD_TOKEN')
DB_URL = os.getenv('DATABASE_URL')
PREMIUM_ROLE_ID = os.getenv('PREMIUM_ROLE_ID')
stripe.api_key = os.getenv(EnvVariables.STRIPE_SECRET_KEY.value)
COMMAND_PREFIX = '@'

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True
intents.members = True
intents.reactions = True
intents.typing = False
intents.presences = False


async def main() -> None:
    """Start the bot."""
    init_db()
    bot = DiscordBot(command_prefix=COMMAND_PREFIX, db_url=DB_URL)
    await bot.start(TOKEN)


if __name__ == '__main__':
    asyncio.run(main())
