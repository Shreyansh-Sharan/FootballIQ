"""Runtime settings from environment variables; secrets stay out of the repo (see ``.env.example``)."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path | None = None) -> list[str]:
    """Load KEY=VALUE lines from the repo-root .env without overriding set variables; returns the names set."""
    path = path or Path(os.environ.get("FOOTBALLIQ_ENV_FILE", REPO_ROOT / ".env"))
    if not path.is_file():
        return []
    loaded = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        key, value = key.strip(), value.strip()
        if value[:1] in "\"'" and value[-1:] == value[:1] and len(value) >= 2:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if key and value and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def data_dir() -> Path:
    return Path(os.environ.get("FOOTBALLIQ_DATA_DIR", REPO_ROOT / "data"))


def bronze_dir() -> Path:
    return data_dir() / "bronze"


def silver_dir() -> Path:
    return data_dir() / "silver"


def cors_origins() -> list[str]:
    raw = os.environ.get("FOOTBALLIQ_CORS_ORIGINS", "http://localhost:3000")
    return [o.strip() for o in raw.split(",") if o.strip()]


# reference match: World Cup 2022 final
STATSBOMB_FINAL_MATCH_ID = 3869685
STATSBOMB_WC2022 = {"competition_id": 43, "season_id": 106}
PFF_FINAL_GAME_ID = 10517
