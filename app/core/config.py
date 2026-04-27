from typing import Optional
from pydantic_settings import BaseSettings

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class Settings(BaseSettings):
    # google oauth (used for calendar)
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REDIRECT_URI: str

    # outlook oauth (used for calendar)
    OUTLOOK_CLIENT_ID: str
    OUTLOOK_CLIENT_SECRET: str
    OUTLOOK_REDIRECT_URI: str

    # DB backend selector: "dynamodb" | "postgresql"
    DB_BACKEND: str = "dynamodb"

    # PostgreSQL (used when DB_BACKEND=postgresql)
    DB_USER: Optional[str] = None
    DB_PASSWORD: Optional[str] = None
    DB_HOST: Optional[str] = None
    DB_PORT: int = 5432
    DB_NAME: Optional[str] = None

    @property
    def DATABASE_URL(self) -> str:
        from urllib.parse import quote_plus
        return f"postgresql://{self.DB_USER}:{quote_plus(self.DB_PASSWORD)}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

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

    # django client secret
    DJANGO_SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    REFRESH_TOKEN_EXPIRE_DAYS: int

    # Email service
    EMAIL_HOST: str
    EMAIL_PORT: int
    EMAIL_HOST_USER: str
    EMAIL_HOST_PASSWORD: str

    # Site url (used in send mail)
    SITE_URL: str

    class Config:
        # Primary: app/.env (where the file actually lives)
        # Fallback: project root .env
        env_file = [
            os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),  # app/.env
            os.path.join(BASE_DIR, ".env"),                                     # project root .env
        ]
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
