from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Paper Code Trace Workbench"
    app_env: str = "local"
    database_url: str = "sqlite:///./data/workbench.db"
    upload_root: str = "./uploads"
    backend_cors_origins: list[str] | str = Field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"]
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: list[str] | str) -> list[str] | str:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def cors_origins(self) -> list[str]:
        if isinstance(self.backend_cors_origins, str):
            return [self.backend_cors_origins]
        return self.backend_cors_origins


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

