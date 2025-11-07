from datetime import datetime, timedelta, timezone
from typing import Any, Union
from OpenSSL import crypto
from jose import jwt
import bcrypt
import logging
# from typing import Optional, Dict, Tuple
# from fastapi import HTTPException, Request, status
# from fastapi.security import OAuth2
# from fastapi.openapi.models import OAuthFlows as OAuthFlowsModel
# from fastapi.security.utils import get_authorization_scheme_param
from app.core.config import settings

logger = logging.getLogger(__name__)



ALGORITHM = ("HS256", "RS256")


def _now_utc() -> datetime:
    """Return the current UTC time with tzinfo, overridable in tests."""
    return datetime.utcnow().replace(tzinfo=timezone.utc)

# class OAuth2TwoTokensBearer(OAuth2):
#     '''
#     Override OAuth2 class based on FastAPI's OAuth2PasswordBearer to support two tokens bearer to authorise either NEF or CAPIF jtw tokens

#     This implementation takes the Authorization header and splits the token parameter into two tokens, assuming they are separated by a comma. It returns a tuple containing the two tokens.
#     '''
#     def __init__(
#         self,
#         tokenUrl: str,
#         scheme_name: Optional[str] = None,
#         scopes: Optional[Dict[str, str]] = None,
#         description: Optional[str] = None,
#         auto_error: bool = True,
#     ):
#         if not scopes:
#             scopes = {}
#         flows = OAuthFlowsModel(password={"tokenUrl": tokenUrl, "scopes": scopes})
#         super().__init__(
#             flows=flows,
#             scheme_name=scheme_name,
#             description=description,
#             auto_error=auto_error,
#         )

#     async def __call__(self, request: Request) -> Optional[Tuple[str, str]]:
#         authorization: str = request.headers.get("Authorization")
#         scheme, param = get_authorization_scheme_param(authorization)
#         if not authorization or scheme.lower() != "bearer":
#             if self.auto_error:
#                 raise HTTPException(
#                     status_code=status.HTTP_401_UNAUTHORIZED,
#                     detail="Not authenticated",
#                     headers={"WWW-Authenticate": "Bearer"},
#                 )
#             else:
#                 return None

#         try:
#             nef_token, capif_token = param.split(',')
#         except ValueError as ex:
#             return {"token" : param}
        
#         return {"nef_token" : nef_token, "capif_token" : capif_token}
    

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
        logger.error(e)
        
    crtObj = crypto.load_certificate(crypto.FILETYPE_PEM, cert)
    pubKeyObject = crtObj.get_pubkey()
    pubKeyString = crypto.dump_publickey(crypto.FILETYPE_PEM,pubKeyObject)
    return pubKeyString
