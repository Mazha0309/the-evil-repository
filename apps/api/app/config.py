from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_scenarios_root() -> Path:
    module_path = Path(__file__).resolve()
    for parent in module_path.parents:
        candidate = parent / "scenarios"
        if candidate.is_dir():
            return candidate
    return Path("/scenarios")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "The Evil Repository"
    environment: str = "development"
    database_url: str = "sqlite:///./evil-repository-dev.db"
    app_secret: str = "development-only-secret-change-me"
    web_origin: str = "http://127.0.0.1:5173"
    session_cookie_name: str = "evil_session"
    session_cookie_secure: bool = False
    session_ttl_hours: int = 168
    setup_token: str | None = None
    runner_enabled: bool = False
    runner_poll_seconds: float = 2.0

    docker_host: str = "unix:///var/run/docker.sock"
    sandbox_image: str = "evil-repository-sandbox:local"
    sandbox_memory: int = 1_073_741_824
    sandbox_workspace_size: str = "1536m"
    sandbox_nano_cpus: int = 1_000_000_000
    sandbox_pids_limit: int = 256
    sandbox_tool_timeout: int = 30
    sandbox_hard_timeout: int = 10_800
    sandbox_max_output: int = 65_536
    artifact_root: str = "/var/lib/evil-repository/artifacts"
    scenarios_root: Path = Field(default_factory=default_scenarios_root)

    default_soft_seconds: int = 5_400
    default_hard_seconds: int = 10_800
    default_soft_tool_calls: int = 500
    default_hard_tool_calls: int = 1_000
    api_prefix: str = "/api/v1"
    seed_manifest: str | None = Field(default=None)


@lru_cache
def get_settings() -> Settings:
    return Settings()
