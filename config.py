from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List


class Settings(BaseSettings):
    bot_token: str = Field(default="", alias="BOT_TOKEN")
    admin_ids: str = Field(default="0", alias="ADMIN_IDS")
    database_url: str = Field(default="sqlite+aiosqlite:///./data/bot.db", alias="DATABASE_URL")
    port: int = Field(default=8080, alias="PORT")

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def admins(self) -> List[int]:
        try:
            return [
                int(x.strip())
                for x in self.admin_ids.split(",")
                if x.strip() and x.strip() != "0"
            ]
        except Exception:
            return []


settings = Settings()

if not settings.bot_token:
    raise SystemExit("BOT_TOKEN environment variable is required")
