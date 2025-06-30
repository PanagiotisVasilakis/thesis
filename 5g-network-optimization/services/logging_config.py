import logging


def configure_logging(level=logging.INFO,
                       fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s'):
    """Configure application-wide logging.

    This sets up the root logger only if no handlers are configured yet so
    repeated calls have no side effects.
    """
    if not logging.getLogger().handlers:
        logging.basicConfig(level=level, format=fmt)
