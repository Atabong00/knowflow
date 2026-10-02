import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Settings:
    PROJECT_NAME: str = "Kenhub"
    SECRET_KEY: str = os.getenv(
        "SECRET_KEY",
        "dev-secret-key-32-chars-minimum-length-for-security"
    )
    DEBUG: bool = os.getenv("DEBUG", "True").lower() in (
        "true", "1", "t", "y", "yes"
    )

    # Application URL
    APP_BASE_URL: str = os.getenv(
        "APP_BASE_URL",
        "http://localhost:8000"
    )

    # Database Settings
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://wiki_user:wiki_pass@localhost:5432/wiki_db"
    )

    # Keycloak Settings
    KEYCLOAK_SERVER_URL: str = os.getenv(
        "KEYCLOAK_SERVER_URL",
        "http://localhost:8080"
    )

    KEYCLOAK_BACKEND_URL: str = os.getenv(
        "KEYCLOAK_BACKEND_URL",
        os.getenv("KEYCLOAK_SERVER_URL", "http://localhost:8080")
    )

    KEYCLOAK_REALM: str = os.getenv(
        "KEYCLOAK_REALM",
        "employee-portal"
    )

    KEYCLOAK_CLIENT_ID: str = os.getenv(
        "KEYCLOAK_CLIENT_ID",
        "wiki-app"
    )

    KEYCLOAK_CLIENT_SECRET: str = os.getenv(
        "KEYCLOAK_CLIENT_SECRET",
        ""
    )


settings = Settings()
