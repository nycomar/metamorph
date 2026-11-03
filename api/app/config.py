from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_key() -> str:
    """API key from the environment, or from a file we keep off the repo."""
    key = os.environ.get("COMFY_API_KEY", "").strip()
    if key:
        return key
    path = Path(os.environ.get("COMFY_API_KEY_FILE", "/root/.comfy/cloud_key"))
    try:
        return path.read_text().strip()
    except OSError:
        return ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    comfy_base_url: str = "https://cloud.comfy.org"
    comfy_api_key: str = ""
    data_dir: Path = Path("./data")
    max_concurrent_jobs: int = 1
    request_timeout_s: float = 120.0
    image_model: str = "sdxl"

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        if not s.comfy_api_key:
            s.comfy_api_key = _read_key()
        s.data_dir = Path(s.data_dir)
        (s.data_dir / "uploads").mkdir(parents=True, exist_ok=True)
        (s.data_dir / "takes").mkdir(parents=True, exist_ok=True)
        (s.data_dir / "exports").mkdir(parents=True, exist_ok=True)
        return s


settings = Settings.load()
