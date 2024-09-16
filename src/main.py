# main.py

import asyncio
import logging.config
import os


import stripe
from dotenv import load_dotenv

from src.core.constants import EnvVariables
from src.config.logger import LOGGING
from src.core.database import init_db
from src.bot.discord_bot import DiscordBot


load_dotenv()


logging.config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)


TOKEN = os.getenv(EnvVariables.DISCORD_BOT_TOKEN.value)
PREMIUM_ROLE_ID = os.getenv(EnvVariables.PREMIUM_ROLE_ID.value)
STRIPE_SECRET_KEY = os.getenv(EnvVariables.STRIPE_SECRET_KEY.value)
COMMAND_PREFIX = '!'

if not TOKEN:
    logger.critical("DISCORD_BOT_TOKEN environment variable not set.")
    raise EnvironmentError("DISCORD_BOT_TOKEN environment variable not set.")

if not STRIPE_SECRET_KEY:
    logger.critical("STRIPE_SECRET_KEY environment variable not set.")
    raise EnvironmentError("STRIPE_SECRET_KEY environment variable not set.")

stripe.api_key = STRIPE_SECRET_KEY


async def main() -> None:
    """Initialize and start the Discord bot."""
    try:
        init_db()
    except Exception as e:
        logger.critical(f"Failed to initialize the database: {e}")
        return

    bot = DiscordBot(command_prefix=COMMAND_PREFIX)

    await asyncio.create_task(bot.start_http_server())

    try:
        await bot.start(TOKEN)
    except Exception as e:
        logger.error(f"Bot encountered an error: {e}", exc_info=True)
    finally:
        await bot.close()


if __name__ == '__main__':
    asyncio.run(main())
