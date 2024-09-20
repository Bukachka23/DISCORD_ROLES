import logging.config
import time
from typing import Generator, Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.orm import sessionmaker, Session

from src.config.logger import LOGGING
from src.config.settings import EnvSettings
from src.core.models import User, Base


load_dotenv()


logging.config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)


DATABASE_URL = EnvSettings.DATABASE_URL

if not DATABASE_URL:
    logger.critical("DATABASE_URL environment variable not set.")
    raise EnvironmentError("DATABASE_URL environment variable not set.")

try:
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True
    )
    logger.info("Database engine created successfully.")
except SQLAlchemyError as e:
    logger.critical(f"Failed to create database engine: {e}")
    raise

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False
)


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
    def _create_tables() -> None:
        """
        Creates all tables defined in the Base metadata.
        """
        try:
            Base.metadata.create_all(bind=engine)
            logger.debug("Database tables created successfully.")
        except SQLAlchemyError as e:
            logger.critical(f"Error creating database tables: {e}")
            raise

    def add_or_update_user(self, user: User) -> None:
        """
        Adds a new user to the database or updates an existing user's information.

        Args:
            user (User): The User instance to add or update.
        """
        logger.info(f"Adding/updating user: {user.discord_id} - {user.username}")
        with self.session_factory() as session:
            try:
                existing_user = session.query(User).filter(User.discord_id == user.discord_id).first()
                if existing_user:
                    logger.debug(f"User {user.discord_id} exists. Updating information.")
                    existing_user.username = user.username
                    existing_user.subscription_start = user.subscription_start
                    existing_user.subscription_end = user.subscription_end
                else:
                    logger.debug(f"User {user.discord_id} does not exist. Adding new user.")
                    session.add(user)
                session.commit()
                logger.debug(f"User {user.discord_id} added/updated successfully.")
            except IntegrityError as e:
                logger.error(f"IntegrityError when adding/updating user {user.discord_id}: {e}")
                session.rollback()
                raise
            except SQLAlchemyError as e:
                logger.error(f"SQLAlchemyError when adding/updating user {user.discord_id}: {e}")
                session.rollback()
                raise

    def get_user_by_discord_id(self, discord_id: str) -> Optional[User]:
        """
        Retrieves a user from the database by their Discord ID.

        Args:
            discord_id (str): The Discord ID of the user.

        Returns:
            Optional[User]: The User instance if found, else None.
        """
        logger.info(f"Retrieving user with Discord ID: {discord_id}")
        with self.session_factory() as session:
            try:
                user = session.query(User).filter(User.discord_id == discord_id).first()
                if user:
                    logger.debug(f"User {discord_id} found.")
                else:
                    logger.debug(f"User {discord_id} not found.")
                return user
            except SQLAlchemyError as e:
                logger.error(f"Error retrieving user {discord_id}: {e}")
                return None

    def get_user_by_user_id(self, user_id: int) -> Optional[User]:
        """
        Retrieves a user from the database by their internal user ID.

        Args:
            user_id (int): The internal user ID.

        Returns:
            Optional[User]: The User instance if found, else None.
        """
        logger.info(f"Retrieving user with User ID: {user_id}")
        with self.session_factory() as session:
            try:
                user = session.query(User).filter(User.id == user_id).first()
                if user:
                    logger.debug(f"User {user_id} found.")
                else:
                    logger.debug(f"User {user_id} not found.")
                return user
            except SQLAlchemyError as e:
                logger.error(f"Error retrieving user {user_id}: {e}")
                return None

    def check_and_reset_sequence(self, table_name: str, primary_key: str) -> None:
        """
        Checks and resets the sequence for the primary key if it is out of sync.

        Args:
            table_name (str): The name of the table.
            primary_key (str): The primary key column name.
        """
        logger.info(f"Checking and resetting sequence for {table_name}.{primary_key}")
        with self.session_factory() as session:
            try:
                max_id = session.execute(text(f"SELECT MAX({primary_key}) FROM {table_name}")).scalar()
                next_val = session.execute(text(f"SELECT nextval(pg_get_serial_sequence('{table_name}', '{primary_key}'))")).scalar()
                logger.debug(f"Max ID: {max_id}, Next Value: {next_val}")

                if max_id is not None and next_val is not None and max_id >= next_val:
                    new_val = max_id + 1
                    session.execute(text(f"SELECT setval(pg_get_serial_sequence('{table_name}', '{primary_key}'), {new_val})"))
                    session.commit()
                    logger.info(f"Sequence for {table_name}.{primary_key} reset to {new_val}")
                else:
                    logger.debug("No need to reset sequence.")
            except SQLAlchemyError as e:
                logger.error(f"Error checking/resetting sequence for {table_name}.{primary_key}: {e}")
                session.rollback()
                raise


def init_db(max_retries: int = 5, retry_delay: int = 5) -> None:
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
            logger.debug("Dropping all tables.")
            Base.metadata.drop_all(bind=engine)
            logger.debug("Creating all tables.")
            Base.metadata.create_all(bind=engine)
            logger.info("Database tables dropped and created successfully.")
            return
        except SQLAlchemyError as e:
            logger.error(f"Error initializing database (Attempt {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                logger.critical("Unable to initialize database after multiple attempts.")
                raise ConnectionError("Unable to initialize database after multiple attempts.") from e


def get_db() -> Generator[Session, None, None]:
    """
    Dependency that yields a database session and ensures it's closed after use.

    Yields:
        Generator[Session, None, None]: A SQLAlchemy Session instance.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
