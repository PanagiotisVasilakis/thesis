import logging
import os
from pathlib import Path
import sys
from tenacity import after_log, before_log, retry, stop_after_attempt, wait_fixed
from app.db.session import SessionLocal


sys.path.append(str(Path(__file__).resolve().parents[4]))
from logging_config import configure_logging
logger = logging.getLogger(__name__)

max_tries = 60
wait_seconds = 1


@retry(
    stop=stop_after_attempt(max_tries),
    wait=wait_fixed(wait_seconds),
    before=before_log(logger, logging.INFO),
    after=after_log(logger, logging.WARN),
)
def init() -> None:
    try:
        db = SessionLocal()
        # Try to create session to check if DB is awake
        db.execute("SELECT 1")
    except Exception as e:
        logger.error(e)
        raise e


    
        
def main() -> None:
    logger.info("Initializing service")
    init()
    logger.info("Service finished initializing")


if __name__ == "__main__":
    configure_logging(level=os.getenv("LOG_LEVEL"), log_file=os.getenv("LOG_FILE"))
    main()
