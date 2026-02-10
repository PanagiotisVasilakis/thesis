from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from pymongo import MongoClient
import os
from app.core.config import settings
from app.core.env_utils import parse_env_int

# SQLAlchemy connection pool configuration (via env vars for tuning)
_pool_size = parse_env_int("SQLALCHEMY_POOL_SIZE", 150, min_value=1, max_value=500)
_max_overflow = parse_env_int("SQLALCHEMY_MAX_OVERFLOW", 20, min_value=0, max_value=100)

engine = create_engine(
    settings.SQLALCHEMY_DATABASE_URI,
    pool_pre_ping=True,
    pool_size=_pool_size,
    max_overflow=_max_overflow,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# MongoDB credentials from environment variables (required - no insecure defaults)
_mongo_username = os.environ.get("MONGO_USER") or os.environ.get("MONGO_USERNAME")
_mongo_password = os.environ.get("MONGO_PASSWORD")
if not _mongo_username or not _mongo_password:
    raise EnvironmentError("MONGO_USER and MONGO_PASSWORD environment variables are required")
client = MongoClient(settings.MONGO_CLIENT, username=_mongo_username, password=_mongo_password)

