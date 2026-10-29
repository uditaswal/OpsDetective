from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./opsdetective.db"
    admin_email: str = "admin@example.invalid"
    admin_password: str = ""
    session_secret: str = ""
    secure_cookies: bool = False
    tenant_id: str = "local"

    model_config = SettingsConfigDict(env_file=None)


settings = Settings()
