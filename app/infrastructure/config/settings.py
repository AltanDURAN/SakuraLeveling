from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    discord_token: str
    database_url: str
    env: str = "development"
    debug: bool = True
    beta_channel_id: int

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()