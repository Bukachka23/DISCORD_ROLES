import asyncio
import logging.config

import stripe
from dotenv import load_dotenv

from src.config.logger import LOGGING
from src.config.settings import EnvSettings
from src.core.database import init_db
from src.bot.discord_bot import DiscordBot


load_dotenv()


logging.config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Initialize and start the Discord bot."""
    try:
        init_db()
    except Exception as e:
        logger.critical(f"Failed to initialize the database: {e}")
        return

    stripe.api_key = EnvSettings.STRIPE_SECRET_KEY
    bot = DiscordBot(
        command_prefix=EnvSettings.COMMAND_PREFIX,
        premium_role_id=int(EnvSettings.PREMIUM_ROLE_ID),
        admin_user_id=int(EnvSettings.ADMIN_USER_ID)
    )

    await asyncio.create_task(bot.start_http_server())

    try:
        await bot.start(EnvSettings.DISCORD_BOT_TOKEN)
    except Exception as e:
        logger.error(f"Bot encountered an error: {e}", exc_info=True)
    finally:
        await bot.close()


if __name__ == '__main__':
    asyncio.run(main())
