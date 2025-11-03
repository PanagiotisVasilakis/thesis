import logging
import os
from pathlib import Path
import sys
from tenacity import after_log, before_log, retry, stop_after_attempt, wait_fixed
from app.db.session import SessionLocal


def _import_logging_config():
    try:
        repo_root = Path(__file__).resolve()
        # Walk up cautiously to avoid IndexError on shallow paths
        for _ in range(4):
            repo_root = repo_root.parent
            if repo_root == repo_root.parent:
                break
        sys.path.append(str(repo_root))
        from logging_config import configure_logging  # type: ignore

        return configure_logging
    except (ImportError, FileNotFoundError):
        def _configure_logging(level=None, log_file=None):
            logging.basicConfig(level=level or logging.INFO)

        return _configure_logging


configure_logging = _import_logging_config()
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
