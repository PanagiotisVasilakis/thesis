import secrets
import json
from typing import Any, List, Optional, Union
from urllib.parse import quote_plus

from pydantic import (
    AnyHttpUrl,
    EmailStr,
    ValidationInfo,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # ----- API & Auth -----
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = secrets.token_urlsafe(32)
    # 60 minutes * 24 hours * 8 days = 8 days
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8

    # ----- Server -----
    SERVER_NAME: str
    SERVER_HOST: str  # changed from AnyHttpUrl to plain string for 0.0.0.0 binding

    # ----- CORS -----
    BACKEND_CORS_ORIGINS: List[str] = []

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    def assemble_cors_origins(
        cls, v: Union[str, List[str]]
    ) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # ----- Project -----
    PROJECT_NAME: str = "My Awesome Project"
    SENTRY_DSN: Optional[AnyHttpUrl] = None

    @field_validator("SENTRY_DSN", mode="before")
    def sentry_dsn_can_be_blank(cls, v: Optional[str]) -> Optional[str]:
        return v or None

    # ----- Database -----
    POSTGRES_SERVER: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    SQLALCHEMY_DATABASE_URI: Optional[str] = None

    @field_validator("SQLALCHEMY_DATABASE_URI", mode="before")
    def assemble_db_connection(
        cls, v: Optional[str], info: ValidationInfo
    ) -> Optional[str]:
        if isinstance(v, str) and v:
            return v
        values = info.data or {}
        user = values.get("POSTGRES_USER")
        password = values.get("POSTGRES_PASSWORD")
        host = values.get("POSTGRES_SERVER")
        database = values.get("POSTGRES_DB")

        if not all([user, password, host, database]):
            return None

        path = f"/{database}" if not str(database).startswith("/") else str(database)

        user_enc = quote_plus(str(user))
        password_enc = quote_plus(str(password))

        return f"postgresql://{user_enc}:{password_enc}@{host}{path}"

    # ----- MongoDB -----
    MONGO_CLIENT: str

    # ----- CAPIF -----
    CAPIF_HOST: str
    CAPIF_HTTP_PORT: str
    CAPIF_HTTPS_PORT: str

    # ----- ML Service -----
    ML_SERVICE_URL: str = "http://ml-service:5050"

    # ----- User Management -----
    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str
    USERS_OPEN_REGISTRATION: bool = False
    USE_PUBLIC_KEY_VERIFICATION: bool

settings = Settings()


class QoSSettings:
    """Load QoS characteristics from JSON file."""

    def __init__(self) -> None:
        self.import_json()

    def import_json(self):
        base = __file__.rsplit("/", 1)[0]
        path = f"{base}/config/qosCharacteristics.json"
        with open(path) as json_file:
            data = json.load(json_file)
        self._qos_characteristics = data

    def retrieve_settings(self):
        return self._qos_characteristics


qosSettings = QoSSettings()
