from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    database_url: str = "sqlite:///./opsdetective.db"
    admin_email: str = "admin@example.invalid"
    admin_password: str = ""
    session_secret: str = ""
    secure_cookies: bool = False
    tenant_id: str = "local"
    internal_api_key: str = ""
    demo_faults_enabled: bool = False
    demo_control_key: str = ""
    prometheus_url: str = "http://prometheus:9090"
    health_stale_seconds: int = Field(default=60, ge=30, le=300)
    health_error_rate_percent: float = Field(default=5, gt=0, le=100)
    health_latency_p95_ms: float = Field(default=500, gt=0, le=60000)

    model_config = SettingsConfigDict(env_file=None)


settings = Settings()
