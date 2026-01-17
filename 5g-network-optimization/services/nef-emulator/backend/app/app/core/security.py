from datetime import datetime, timedelta, timezone
from typing import Any, Union
from OpenSSL import crypto
from jose import jwt
import bcrypt
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)



ALGORITHM = ("HS256", "RS256")


def _now_utc() -> datetime:
    """Return the current UTC time with tzinfo, overridable in tests."""
    return datetime.now(timezone.utc)




def create_access_token(
    subject: Union[str, Any], expires_delta: timedelta = None
) -> str:
    if expires_delta:
        expire = _now_utc() + expires_delta
    else:
        expire = _now_utc() + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM[0])
    return encoded_jwt


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return ``True`` if ``plain_password`` matches ``hashed_password``."""

    if hashed_password is None:
        return False

    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except ValueError:
        # if hashed_password has invalid format
        return False


def get_password_hash(password: str) -> str:
    """Hash ``password`` using bcrypt."""

    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def extract_public_key(cert_path: str):
    try:
        with open(cert_path, 'r') as f:
            cert = f.read()
    except FileNotFoundError as e:
        logger.error("Certificate file not found: %s", cert_path)
        raise  # Re-raise to prevent crash on undefined 'cert' variable

    crtObj = crypto.load_certificate(crypto.FILETYPE_PEM, cert)
    pubKeyObject = crtObj.get_pubkey()
    pubKeyString = crypto.dump_publickey(crypto.FILETYPE_PEM, pubKeyObject)
    return pubKeyString
