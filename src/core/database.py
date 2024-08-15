import logging.config
import os
import time
from typing import Type

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from src.config.log_config import LOGGING
from src.core.constants import EnvVariables
from src.core.models import User, Base

load_dotenv()

logging.config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)

database_url = os.getenv(EnvVariables.DATABASE_URL.value)


def create_db_engine():
    try:
        engine = create_engine(database_url, echo=True)
        return engine
    except SQLAlchemyError as e:
        logger.error(f"Error creating database engine: {e!s}")
        raise


engine = create_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class DatabaseManager:
    def __init__(self, db_url: str):
        logger.info(f"Initializing DatabaseManager with URL: {db_url}")
        self.engine = create_engine(db_url)
        self.Session = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)
        logger.debug("Database tables created")

    def add_user(self, user: User) -> None:
        """Add a new user to the database."""
        logger.info(f"Adding user: {user.user_id} - {user.username}")
        with self.Session() as session:
            user_model = User(
                user_id=user.user_id,
                username=user.username,
                subscription_start=user.subscription_start,
                subscription_end=user.subscription_end
            )
            session.add(user_model)
            try:
                session.commit()
                logger.debug(f"User {user.user_id} added successfully")
            except Exception as e:
                logger.error(f"Error adding user {user.user_id}: {e!s}")
                session.rollback()
                raise

    def get_user(self, user_id: int) -> Type[User] | None:
        """Get a user from the database."""
        logger.info(f"Getting user with ID: {user_id}")
        with self.Session() as session:
            user_model = session.query(User).filter_by(user_id=user_id).first()
            if user_model:
                logger.debug(f"User {user_id} found")
                return user_model
            logger.debug(f"User {user_id} not found")
            return None


def init_db() -> None:
    """Create tables in the database."""
    max_retries = 5
    retry_delay = 5

    for attempt in range(max_retries):
        try:
            Base.metadata.drop_all(bind=engine)
            Base.metadata.create_all(bind=engine)
            logger.info("Database tables dropped and recreated successfully")
            return
        except SQLAlchemyError as e:
            logger.error(f"Error initializing database (Attempt {attempt + 1}/{max_retries}): {e!s}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                raise ConnectionError("Unable to initialize database after multiple attempts")


def get_db():
    """Get the database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
