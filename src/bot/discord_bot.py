import asyncio
import logging.config

import discord
from discord.ext import commands
from aiohttp import web
from src.config.log_config import LOGGING
from src.bot.commands import CommandHandler
from src.core.database import DatabaseManager, get_db

logging.config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)


class DiscordBot(commands.Bot):
    def __init__(self, command_prefix: str, db_url: str):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix=command_prefix, intents=intents)

        self.db_manager = DatabaseManager(db_url)
        self.logger = logging.getLogger(__name__)

    async def get_context(self, message, *, cls=commands.Context) -> commands.Context:
        """Override the get_context method to handle custom prefixes."""
        ctx = await super().get_context(message, cls=cls)
        if ctx.prefix is not None and ctx.invoked_with:
            ctx.command = self.all_commands.get(ctx.invoked_with.lower())
            if ctx.command is None:
                words = message.content[len(ctx.prefix):].split()
                for i in range(1, len(words)):
                    cmd_name = ' '.join(words[:i + 1]).lower()
                    if cmd_name in self.all_commands:
                        ctx.command = self.all_commands[cmd_name]
                        ctx.invoked_with = cmd_name
                        break
        return ctx

    @staticmethod
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
        logger.info("HTTP server started for health checks on port 80")

    async def setup_hook(self) -> None:
        """Set up the bot by adding cogs and loading commands."""
        command_handler = CommandHandler(self, self.db_manager)
        await self.add_cog(command_handler)
        await self.tree.sync()
        self.logger.info("CommandHandler cog loaded")

    async def on_ready(self):
        """Log bot information when it is ready."""
        self.logger.info(f'{self.user} has connected to Discord!')
        self.logger.info(f'Guilds: {", ".join([guild.name for guild in self.guilds])}')
        self.logger.info(f'Command prefix: {self.command_prefix}')
        self.logger.info(f'Registered commands: {", ".join([cmd.name for cmd in self.commands])}')

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        """Handle command errors."""
        if isinstance(error, commands.CommandNotFound):
            await ctx.author.send(f"Invalid command: {ctx.message.content}. Please try again.")
            self.logger.warning("Invalid command used: %s", ctx.message.content)
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.author.send(f"Missing required argument: {error.param}")
            self.logger.warning("Missing required argument: %s", error)
        elif isinstance(error, commands.CommandInvokeError):
            if isinstance(error.original, asyncio.TimeoutError):
                await ctx.author.send("The command timed out. Please try again.")
                self.logger.warning("Command timed out: %s", ctx.command.name)
            else:
                await ctx.author.send(f"An error occurred: {error.original}")
                self.logger.error("Command invoke error: %s", error.original, exc_info=True)
        else:
            await ctx.author.send(f"An error occurred: {error!s}")
            self.logger.error("An error occurred: %s", error, exc_info=True)
