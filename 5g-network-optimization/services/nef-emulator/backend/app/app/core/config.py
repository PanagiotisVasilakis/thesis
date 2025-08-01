import secrets
import json
from typing import Any, Dict, List, Optional, Union

from pydantic import (
    AnyHttpUrl,
    BaseSettings,
    EmailStr,
    PostgresDsn,
    validator,
)


class Settings(BaseSettings):
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

    @validator("BACKEND_CORS_ORIGINS", pre=True, allow_reuse=True)
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

    @validator("SENTRY_DSN", pre=True, allow_reuse=True)
    def sentry_dsn_can_be_blank(cls, v: str) -> Optional[str]:
        if not v:
            return None
        return v

    # ----- Database -----
    POSTGRES_SERVER: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    SQLALCHEMY_DATABASE_URI: Optional[PostgresDsn] = None

    @validator("SQLALCHEMY_DATABASE_URI", pre=True, allow_reuse=True)
    def assemble_db_connection(
        cls, v: Optional[str], values: Dict[str, Any]
    ) -> Any:
        if isinstance(v, str):
            return v
        return PostgresDsn.build(
            scheme="postgresql",
            user=values.get("POSTGRES_USER"),
            password=values.get("POSTGRES_PASSWORD"),
            host=values.get("POSTGRES_SERVER"),
            path=f"/{values.get('POSTGRES_DB') or ''}",
        )

    # ----- MongoDB -----
    MONGO_CLIENT: str

    # ----- Rate Limiter -----
    REDIS_URL: str = "redis://localhost:6379"

    # ----- CAPIF -----
    CAPIF_HOST: str
    CAPIF_HTTP_PORT: str
    CAPIF_HTTPS_PORT: str

    # ----- ML Service -----
    ML_SERVICE_URL: str = "http://ml-service:5050"

    # ----- Email -----
    SMTP_TLS: bool = True
    SMTP_PORT: Optional[int] = None
    SMTP_HOST: Optional[str] = None
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    EMAILS_FROM_EMAIL: Optional[EmailStr] = None
    EMAILS_FROM_NAME: Optional[str] = None

    @validator("EMAILS_FROM_NAME", allow_reuse=True)
    def get_project_name(
        cls, v: Optional[str], values: Dict[str, Any]
    ) -> str:
        return v or values["PROJECT_NAME"]

    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48
    EMAIL_TEMPLATES_DIR: str = "/app/app/email-templates/build"
    EMAILS_ENABLED: bool = False

    @validator("EMAILS_ENABLED", pre=True, allow_reuse=True)
    def get_emails_enabled(cls, v: bool, values: Dict[str, Any]) -> bool:
        return bool(
            values.get("SMTP_HOST")
            and values.get("SMTP_PORT")
            and values.get("EMAILS_FROM_EMAIL")
        )

    # ----- User Management -----
    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str
    USERS_OPEN_REGISTRATION: bool = False
    USE_PUBLIC_KEY_VERIFICATION: bool

    class Config:
        case_sensitive = True
        env_file = ".env"
        env_file_encoding = "utf-8"


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
