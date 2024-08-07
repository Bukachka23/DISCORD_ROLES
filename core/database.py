import os

from dotenv import load_dotenv

from core.models import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from bot.constants import EnvVariables

load_dotenv()

database_url = os.getenv(EnvVariables.DATABASE_URL.value)

if not database_url:
    raise ValueError("DATABASE_URL environment variable is not set")

engine = create_engine(database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create tables in the database."""
    Base.metadata.create_all(bind=engine)


def get_db() -> SessionLocal:
    """Get the database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
