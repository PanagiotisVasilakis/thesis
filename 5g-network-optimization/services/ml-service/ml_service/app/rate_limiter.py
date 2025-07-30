"""Flask-Limiter initialization."""
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


limiter = Limiter(key_func=get_remote_address, default_limits=["100 per minute"])


def init_app(app):
    """Initialize limiter with the given Flask ``app``."""
    limiter.init_app(app)
    return limiter
