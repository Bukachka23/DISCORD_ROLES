import asyncio
import logging.config

import discord
from aiohttp import web
from discord.ext import commands

from src.bot.commands import CommandHandler
from src.config.logger import LOGGING
from src.core.database import get_db

logging.config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)


class DiscordBot(commands.Bot):
    """Custom Discord bot with extended functionalities."""

    def __init__(self, command_prefix: str):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix=command_prefix, intents=intents)

        self.logger = logging.getLogger(__name__)

    @staticmethod
    async def health_check(_) -> web.Response:
        """
        Health check endpoint for the HTTP server.

        Returns a JSON response indicating the health status of the bot and database.
        """
        logger.info("Health check requested")
        try:
            db = next(get_db())
            db.execute("SELECT 1")
            db.close()
            logger.info("Database connection successful")
            return web.json_response({'status': 'ok'})
        except Exception as e:
            logger.error(f"Health check failed: {e!s}")
            return web.json_response({'status': 'error', 'message': str(e)}, status=500)

    async def start_http_server(self) -> None:
        """Start the HTTP server for health checks."""
        app = web.Application()
        app.router.add_get('/health', self.health_check)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', 8080)
        await site.start()
        logger.info("HTTP server started for health checks on port 8080")

    async def setup_hook(self) -> None:
        """
        Set up the bot by adding cogs and loading commands.

        This method is called before the bot starts.
        """
        command_handler = CommandHandler(self)
        await self.add_cog(command_handler)
        await self.tree.sync()
        self.logger.info("CommandHandler cog loaded")

    async def on_ready(self) -> None:
        """Log bot information when it is ready."""
        self.logger.info(f'{self.user} has connected to Discord!')
        self.logger.info(f'Guilds: {", ".join([guild.name for guild in self.guilds])}')
        self.logger.info(f'Command prefix: {self.command_prefix}')
        self.logger.info(f'Registered commands: {", ".join([cmd.name for cmd in self.commands])}')

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        """
        Handle command errors.

        Provides user feedback and logs the error for debugging.
        """
        if isinstance(error, commands.CommandNotFound):
            await ctx.author.send(f"Invalid command: `{ctx.message.content}`. Please try again.")
            self.logger.warning(f"Invalid command used: {ctx.message.content}")

        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.author.send(f"Missing required argument: `{error.param.name}`.")
            self.logger.warning(f"Missing required argument in command: {error}")

        elif isinstance(error, commands.CommandInvokeError):
            if isinstance(error.original, asyncio.TimeoutError):
                await ctx.author.send("The command timed out. Please try again.")
                self.logger.warning(f"Command timed out: {ctx.command.name}")
            else:
                await ctx.author.send(f"An error occurred: `{error.original}`.")
                self.logger.error(f"Command invoke error in `{ctx.command.name}`: {error.original}", exc_info=True)

        else:
            await ctx.author.send(f"An unexpected error occurred: `{error}`.")
            self.logger.error(f"Unexpected error in `{ctx.command}`: {error}", exc_info=True)
