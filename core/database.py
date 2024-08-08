import os
import time
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from core.models import Base
from bot.constants import EnvVariables

load_dotenv()

database_url = os.getenv(EnvVariables.DATABASE_URL.value)


def create_db_engine():
    try:
        endpoint = database_url.split('@')[1].split('.')[0]
        new_database_url = f"{database_url}?options=endpoint%3D{endpoint}"
        engine = create_engine(new_database_url, echo=True)
        return engine
    except SQLAlchemyError as e:
        print(f"Error creating database engine: {str(e)}")
        raise


engine = create_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create tables in the database."""
    max_retries = 5
    retry_delay = 5

    for attempt in range(max_retries):
        try:
            Base.metadata.create_all(bind=engine)
            print("Database tables created successfully")
            return
        except SQLAlchemyError as e:
            print(f"Error creating database tables (Attempt {attempt + 1}/{max_retries}): {str(e)}")
            if attempt < max_retries - 1:
                print(f"Retrying in {retry_delay} seconds...")
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
