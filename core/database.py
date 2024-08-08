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

if not database_url:
    raise ValueError("DATABASE_URL environment variable is not set")


def create_db_engine():
    try:
        engine = create_engine(database_url, echo=True)
        return engine
    except SQLAlchemyError as e:
        print(f"Error creating database engine: {str(e)}")
        raise


engine = create_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def test_db_connection():
    try:
        with engine.connect() as connection:
            connection.execute("SELECT 1")
        print("Database connection successful")
        return True
    except SQLAlchemyError as e:
        print(f"Database connection failed: {str(e)}")
        return False


def init_db() -> None:
    """Create tables in the database."""
    max_retries = 5
    retry_delay = 5

    for attempt in range(max_retries):
        if test_db_connection():
            try:
                Base.metadata.create_all(bind=engine)
                print("Database tables created successfully")
                return
            except SQLAlchemyError as e:
                print(f"Error creating database tables: {str(e)}")
                raise
        else:
            print(f"Unable to connect to the database. Retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)

    raise ConnectionError("Unable to initialize database after multiple attempts")


def get_db():
    """Get the database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
