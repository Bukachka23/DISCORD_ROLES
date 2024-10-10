import asyncio
import logging.config
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.config.logger import LOGGING
from src.config.settings import EnvSettings
from src.core.models import Base, User

logging.config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)

DATABASE_URL = EnvSettings.DATABASE_URL

if not DATABASE_URL:
    logger.critical("DATABASE_URL environment variable not set.")
    raise EnvironmentError("DATABASE_URL environment variable not set.")

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class DatabaseManager:
    """Manages database operations using SQLAlchemy sessions."""

    def __init__(self, session_factory: sessionmaker):
        """Initialize the DatabaseManager with a session factory."""
        self.session_factory = session_factory
        asyncio.run(self._create_tables())

    @staticmethod
    async def _create_tables() -> None:
        """Create all tables defined in the Base metadata."""
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.debug("Database tables created successfully.")
        except SQLAlchemyError as e:
            logger.critical(f"Error creating database tables: {e}")
            raise

    async def add_or_update_user(self, user: User) -> None:
        """Add a new user to the database or update an existing user's information."""
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
        """Retrieve a user from the database by their Discord ID."""
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

    async def check_and_reset_sequence(self, table_name: str, primary_key: str) -> None:
        """Check and reset the sequence for the primary key if it is out of sync."""
        logger.info(f"Checking and resetting sequence for {table_name}.{primary_key}")
        async with self.session_factory() as session:
            try:
                max_id_result = await session.execute(text(f"SELECT MAX({primary_key}) FROM {table_name}"))
                max_id = max_id_result.scalar()
                next_val_result = await session.execute(
                    text(f"SELECT nextval(pg_get_serial_sequence('{table_name}', '{primary_key}'))")
                )
                next_val = next_val_result.scalar()
                logger.debug(f"Max ID: {max_id}, Next Value: {next_val}")

                if max_id is not None and next_val is not None and max_id >= next_val:
                    new_val = max_id + 1
                    await session.execute(
                        text(f"SELECT setval(pg_get_serial_sequence('{table_name}', '{primary_key}'), {new_val})")
                    )
                    await session.commit()
                    logger.info(f"Sequence for {table_name}.{primary_key} reset to {new_val}")
                else:
                    logger.debug("No need to reset sequence.")
            except SQLAlchemyError as e:
                logger.error(f"Error checking/resetting sequence for {table_name}.{primary_key}: {e}")
                await session.rollback()
                raise


async def init_db(max_retries: int = 5, retry_delay: int = 5) -> None:
    """Initialize the database by dropping and creating all tables."""
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
    """Provide a transactional scope around a series of operations."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            await session.close()
