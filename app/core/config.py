from typing import Optional
from pydantic_settings import BaseSettings

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class Settings(BaseSettings):
    # google oauth (used for calendar)
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: Optional[str] = None

    # outlook oauth (used for calendar)
    OUTLOOK_CLIENT_ID: Optional[str] = None
    OUTLOOK_CLIENT_SECRET: Optional[str] = None
    OUTLOOK_REDIRECT_URI: Optional[str] = None

    # DB backend selector: "dynamodb" | "postgresql"
    DB_BACKEND: str = "dynamodb"

    # PostgreSQL (used when DB_BACKEND=postgresql)
    DB_USER: Optional[str] = None
    DB_PASSWORD: Optional[str] = None
    DB_HOST: Optional[str] = None
    DB_PORT: int = 5432
    DB_NAME: Optional[str] = None
    DB_SSLMODE: Optional[str] = None   # e.g. "require" for CockroachDB / RDS

    @property
    def DATABASE_URL(self) -> str:
        from urllib.parse import quote_plus
        base = f"postgresql://{self.DB_USER}:{quote_plus(self.DB_PASSWORD)}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        if self.DB_SSLMODE:
            base += f"?sslmode={self.DB_SSLMODE}"
        return base

    # AWS / DynamoDB (used when DB_BACKEND=dynamodb)
    AWS_REGION: str = "ap-south-1"
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    DYNAMODB_ENDPOINT_URL: Optional[str] = None  # set for local DynamoDB (e.g. http://localhost:8000)

    # DynamoDB table names (overridable via env)
    TABLE_CALENDAR_ACCOUNTS: str = "calendar_accounts"
    TABLE_CALENDAR_EVENTS: str = "calendar_events"
    TABLE_CALENDAR_PARTICIPANTS: str = "calendar_participants"
    TABLE_USERS: str = "users"
    TABLE_ORGANIZATIONS: str = "organizations"
    TABLE_ORG_AUTH_CONFIGS: str = "org_auth_configs"
    TABLE_USERGROUPS: str = "usergroups"
    TABLE_EMPLOYEES: str = "employees"
    TABLE_EVENT_LOG: str = "event_log"
    TABLE_EMPLOYEE_DETAILS: str = "employee_details"
    TABLE_SCHEMAS: str = "datastore_schemas"

    # django client secret
    DJANGO_SECRET_KEY: Optional[str] = None
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 1

    # Email service
    EMAIL_HOST: Optional[str] = None
    EMAIL_PORT: int = 587
    EMAIL_HOST_USER: Optional[str] = None
    EMAIL_HOST_PASSWORD: Optional[str] = None

    # Site url (used in send mail)
    SITE_URL: Optional[str] = None

    class Config:
        # Primary: app/.env (where the file actually lives)
        # Fallback: project root .env
        env_file = [
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"),  # fastapi_service/.env
            os.path.join(BASE_DIR, ".env"),                                                       # project root .env
        ]
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
