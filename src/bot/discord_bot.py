import asyncio
import logging.config

import discord
from aiohttp import web
from discord.ext import commands

from src.cogs.message_handler import MessageHandler
from src.cogs.payment import PaymentCog
from src.cogs.subscription import SubscriptionCog
from src.cogs.ticket import TicketCog
from src.config.logger import LOGGING
from src.core.database import get_db

logging.config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)


class DiscordBot(commands.Bot):
    """Custom Discord bot with extended functionalities."""

    def __init__(
        self, command_prefix: str, premium_role_id: int, admin_user_id: int
    ):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix=command_prefix, intents=intents)

        self.logger = logging.getLogger(__name__)
        self.premium_role_id = premium_role_id
        self.admin_user_id = admin_user_id

    @staticmethod
    async def health_check(_: web.Request) -> web.Response:
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
            return web.json_response({"status": "ok"})
        except Exception as e:
            logger.error(f"Health check failed: {e!s}")
            return web.json_response(
                {"status": "error", "message": str(e)}, status=500
            )

    async def start_http_server(self) -> None:
        """Start the HTTP server for health checks."""
        app = web.Application()
        app.router.add_get("/health", self.health_check)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", 8080)
        await site.start()
        logger.info("HTTP server started for health checks on port 8080")

    async def setup_hook(self) -> None:
        """
        Set up the bot by adding cogs and loading commands.
        This method is called before the bot starts.
        """
        payment_cog = PaymentCog(
            self, self.premium_role_id, self.admin_user_id
        )
        subscription_cog = SubscriptionCog(
            self, self.premium_role_id, self.admin_user_id
        )
        ticket_cog = TicketCog(
            self, self.premium_role_id, self.admin_user_id
        )
        message_handler = MessageHandler(self)

        await self.add_cog(payment_cog)
        await self.add_cog(subscription_cog)
        await self.add_cog(ticket_cog)
        await self.add_cog(message_handler)

        await self.tree.sync()
        self.logger.info("All cogs loaded successfully")

    async def on_ready(self) -> None:
        """Log bot information when it is ready."""
        self.logger.info(f"{self.user} has connected to Discord!")
        guild_names = ", ".join([guild.name for guild in self.guilds])
        self.logger.info(f"Guilds: {guild_names}")
        self.logger.info(f"Command prefix: {self.command_prefix}")
        command_names = ", ".join([cmd.name for cmd in self.commands])
        self.logger.info(f"Registered commands: {command_names}")

    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        """
        Handle command errors.

        Provides user feedback and logs the error for debugging.
        """
        if isinstance(error, commands.CommandNotFound):
            await self.handle_command_not_found(ctx)
        elif isinstance(error, commands.MissingRequiredArgument):
            await self.handle_missing_argument(ctx, error)
        elif isinstance(error, commands.CommandInvokeError):
            await self.handle_command_invoke_error(ctx, error)
        else:
            await self.handle_unexpected_error(ctx, error)

    async def handle_command_not_found(self, ctx: commands.Context) -> None:
        """Handle CommandNotFound errors."""
        await ctx.author.send(
            f"Invalid command: {ctx.message.content}. Please try again."
        )
        self.logger.warning(f"Invalid command used: {ctx.message.content}")

    async def handle_missing_argument(
        self, ctx: commands.Context, error: commands.MissingRequiredArgument
    ) -> None:
        """Handle MissingRequiredArgument errors."""
        await ctx.author.send(
            f"Missing required argument: {error.param.name}."
        )
        self.logger.warning(f"Missing required argument in command: {error}")

    async def handle_command_invoke_error(
        self, ctx: commands.Context, error: commands.CommandInvokeError
    ) -> None:
        """Handle CommandInvokeError errors."""
        if isinstance(error.original, asyncio.TimeoutError):
            await ctx.author.send("The command timed out. Please try again.")
            self.logger.warning(
                f"Command timed out: {ctx.command.name}"
            )
        else:
            await ctx.author.send(
                f"An error occurred: {error.original}."
            )
            self.logger.error(
                f"Command invoke error in {ctx.command.name}: {error.original}",
                exc_info=True,
            )

    async def handle_unexpected_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        """Handle unexpected errors."""
        await ctx.author.send(
            f"An unexpected error occurred: {error}."
        )
        self.logger.error(
            f"Unexpected error in {ctx.command}: {error}",
            exc_info=True,
        )
