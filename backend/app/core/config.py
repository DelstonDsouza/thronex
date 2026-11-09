from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str

    # Looks for .env in the project root (when running from backend/) or in backend/.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")


settings = Settings()