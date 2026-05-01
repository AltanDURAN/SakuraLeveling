from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    discord_token: str
    database_url: str
    env: str = "development"
    debug: bool = True
    beta_channel_id: int
    encounter_channel_id: int
    admin_discord_ids: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def admin_ids(self) -> list[int]:
        if not self.admin_discord_ids:
            return []
        return [
            int(part.strip())
            for part in self.admin_discord_ids.split(",")
            if part.strip()
        ]


settings = Settings()