import secrets
import json
from typing import Any, Dict, List, Optional, Union

from pydantic import (
    AnyHttpUrl,
    EmailStr,
    PostgresDsn,
    ValidationInfo,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
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
    @classmethod
    def sentry_dsn_can_be_blank(cls, v: Optional[str]) -> Optional[str]:
        return v or None

    # ----- Database -----
    POSTGRES_SERVER: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    SQLALCHEMY_DATABASE_URI: Optional[PostgresDsn] = None

    @field_validator("SQLALCHEMY_DATABASE_URI", mode="before")
    @classmethod
    def assemble_db_connection(
        cls, v: Optional[str], info: ValidationInfo
    ) -> Any:
        if isinstance(v, str):
            return v
        data = info.data
        return PostgresDsn.build(
            scheme="postgresql",
            username=data.get("POSTGRES_USER"),
            password=data.get("POSTGRES_PASSWORD"),
            host=data.get("POSTGRES_SERVER"),
            path=f"{data.get('POSTGRES_DB') or ''}",
        )

    # ----- MongoDB -----
    MONGO_CLIENT: str

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

    @field_validator("EMAILS_FROM_NAME", mode="before")
    @classmethod
    def get_project_name(
        cls, v: Optional[str], info: ValidationInfo
    ) -> str:
        return v or info.data.get("PROJECT_NAME")

    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48
    EMAIL_TEMPLATES_DIR: str = "/app/app/email-templates/build"
    EMAILS_ENABLED: bool = False

    @field_validator("EMAILS_ENABLED", mode="before")
    @classmethod
    def get_emails_enabled(cls, v: bool, info: ValidationInfo) -> bool:
        data = info.data
        return bool(
            data.get("SMTP_HOST")
            and data.get("SMTP_PORT")
            and data.get("EMAILS_FROM_EMAIL")
        )

    # ----- User Management -----
    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str
    USERS_OPEN_REGISTRATION: bool = False
    USE_PUBLIC_KEY_VERIFICATION: bool

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        env_file_encoding="utf-8",
    )


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
