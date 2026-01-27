from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


@dataclass(frozen=True)
class Settings:
    discord_token: str
    briefing_channel_id: int
    log_channel_id: int
    owm_api_key: str
    owm_zip_code: str
    nanogpt_api_key: str

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            discord_token=_require("DISCORD_TOKEN"),
            briefing_channel_id=int(_require("BRIEFING_CHANNEL_ID")),
            log_channel_id=int(_require("LOG_CHANNEL_ID")),
            owm_api_key=_require("OWM_API_KEY"),
            owm_zip_code=_require("OWM_ZIP_CODE"),
            nanogpt_api_key=_require("NANOGPT_API_KEY"),
        )
