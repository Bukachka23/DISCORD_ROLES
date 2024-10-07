import asyncio
import logging.config
from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from dotenv import load_dotenv
from sqlalchemy import text, select
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.orm import sessionmaker

from src.config.logger import LOGGING
from src.config.settings import EnvSettings
from src.core.models import User, Base

load_dotenv()

logging.config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)

DATABASE_URL = EnvSettings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://')

if not DATABASE_URL:
    logger.critical("DATABASE_URL environment variable not set.")
    raise EnvironmentError("DATABASE_URL environment variable not set.")

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class DatabaseManager:
    """
    Manages database operations using SQLAlchemy sessions.
    """

    def __init__(self, session_factory: sessionmaker):
        """
        Initializes the DatabaseManager with a session factory.

        Args:
            session_factory (sessionmaker): A configured sessionmaker instance.
        """
        self.session_factory = session_factory
        self._create_tables()

    @staticmethod
    async def _create_tables() -> None:
        """
        Creates all tables defined in the Base metadata.
        """
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.debug("Database tables created successfully.")
        except SQLAlchemyError as e:
            logger.critical(f"Error creating database tables: {e}")
            raise

    async def add_or_update_user(self, user: User) -> None:
        """
        Adds a new user to the database or updates an existing user's information.

        Args:
            user (User): The User instance to add or update.
        """
        logger.info(f"Adding/updating user: {user.discord_id} - {user.username}")
        async with self.session_factory() as session:
            try:
                existing_user = await session.execute(select(User).filter(User.discord_id == user.discord_id))
                existing_user = existing_user.scalar_one_or_none()
                if existing_user:
                    logger.debug(f"User {user.discord_id} exists. Updating information.")
                    existing_user.username = user.username
                    existing_user.subscription_start = user.subscription_start
                    existing_user.subscription_end = user.subscription_end
                else:
                    logger.debug(f"User {user.discord_id} does not exist. Adding new user.")
                    session.add(user)
                await session.commit()
                logger.debug(f"User {user.discord_id} added/updated successfully.")
            except IntegrityError as e:
                logger.error(f"IntegrityError when adding/updating user {user.discord_id}: {e}")
                await session.rollback()
                raise
            except SQLAlchemyError as e:
                logger.error(f"SQLAlchemyError when adding/updating user {user.discord_id}: {e}")
                await session.rollback()
                raise

    async def get_user_by_discord_id(self, discord_id: str) -> Optional[User]:
        """
        Retrieves a user from the database by their Discord ID.

        Args:
            discord_id (str): The Discord ID of the user.

        Returns:
            Optional[User]: The User instance if found, else None.
        """
        logger.info(f"Retrieving user with Discord ID: {discord_id}")
        async with self.session_factory() as session:
            try:
                result = await session.execute(select(User).filter(User.discord_id == discord_id))
                user = result.scalar_one_or_none()
                if user:
                    logger.debug(f"User {discord_id} found.")
                else:
                    logger.debug(f"User {discord_id} not found.")
                return user
            except SQLAlchemyError as e:
                logger.error(f"Error retrieving user {discord_id}: {e}")
                return None

    async def get_user_by_user_id(self, user_id: int) -> Optional[User]:
        """
        Retrieves a user from the database by their internal user ID.

        Args:
            user_id (int): The internal user ID.

        Returns:
            Optional[User]: The User instance if found, else None.
        """
        logger.info(f"Retrieving user with User ID: {user_id}")
        async with self.session_factory() as session:
            try:
                result = await session.execute(select(User).filter(User.id == user_id))
                user = result.scalar_one_or_none()
                if user:
                    logger.debug(f"User {user_id} found.")
                else:
                    logger.debug(f"User {user_id} not found.")
                return user
            except SQLAlchemyError as e:
                logger.error(f"Error retrieving user {user_id}: {e}")
                return None

    async def check_and_reset_sequence(self, table_name: str, primary_key: str) -> None:
        """
        Checks and resets the sequence for the primary key if it is out of sync.

        Args:
            table_name (str): The name of the table.
            primary_key (str): The primary key column name.
        """
        logger.info(f"Checking and resetting sequence for {table_name}.{primary_key}")
        async with self.session_factory() as session:
            try:
                max_id_result = await session.execute(text(f"SELECT MAX({primary_key}) FROM {table_name}"))
                max_id = max_id_result.scalar()
                next_val_result = await session.execute(
                    text(f"SELECT nextval(pg_get_serial_sequence('{table_name}', '{primary_key}'))"))
                next_val = next_val_result.scalar()
                logger.debug(f"Max ID: {max_id}, Next Value: {next_val}")

                if max_id is not None and next_val is not None and max_id >= next_val:
                    new_val = max_id + 1
                    await session.execute(
                        text(f"SELECT setval(pg_get_serial_sequence('{table_name}', '{primary_key}'), {new_val})"))
                    await session.commit()
                    logger.info(f"Sequence for {table_name}.{primary_key} reset to {new_val}")
                else:
                    logger.debug("No need to reset sequence.")
            except SQLAlchemyError as e:
                logger.error(f"Error checking/resetting sequence for {table_name}.{primary_key}: {e}")
                await session.rollback()
                raise


async def init_db(max_retries: int = 5, retry_delay: int = 5) -> None:
    """
    Initializes the database by dropping and creating all tables.

    Retries on failure up to `max_retries` times with `retry_delay` seconds between attempts.

    Args:
        max_retries (int, optional): Maximum number of retry attempts. Defaults to 5.
        retry_delay (int, optional): Delay in seconds between retries. Defaults to 5.
    """
    logger.info("Initializing the database.")
    for attempt in range(1, max_retries + 1):
        try:
            async with engine.begin() as conn:
                logger.debug("Dropping all tables.")
                await conn.run_sync(Base.metadata.drop_all)
                logger.debug("Creating all tables.")
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables dropped and created successfully.")
            return
        except SQLAlchemyError as e:
            logger.error(f"Error initializing database (Attempt {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                logger.critical("Unable to initialize database after multiple attempts.")
                raise ConnectionError("Unable to initialize database after multiple attempts.") from e


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            await session.close()
