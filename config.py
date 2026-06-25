from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    client_id: str
    client_secret: str
    redirect_uri: str
    secret_key: str
    token_encryption_key: str
    admin_password: str
    timezone: str
    report_hour: int
    report_minute: int
    host: str
    port: int
    group_name: str
    data_dir: Path
    database_path: Path
    report_dir: Path


def _required(name: str, *, required: bool, fallback: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    if required:
        raise RuntimeError(f"{name} ontbreekt in de omgevingsvariabelen.")
    return fallback


def get_settings(require_secrets: bool = True) -> Settings:
    hour = int(os.getenv("REPORT_HOUR", "23"))
    minute = int(os.getenv("REPORT_MINUTE", "59"))
    port = int(os.getenv("PORT", "5000"))
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise RuntimeError("REPORT_HOUR of REPORT_MINUTE is ongeldig.")

    raw_data_dir = os.getenv("DATA_DIR", "./data").strip()
    data_dir = Path(raw_data_dir)
    if not data_dir.is_absolute():
        data_dir = (BASE_DIR / data_dir).resolve()

    return Settings(
        client_id=_required("STRAVA_CLIENT_ID", required=require_secrets, fallback="test-client"),
        client_secret=_required("STRAVA_CLIENT_SECRET", required=require_secrets, fallback="test-secret"),
        redirect_uri=os.getenv("STRAVA_REDIRECT_URI", "http://localhost:5000/callback").strip(),
        secret_key=_required("APP_SECRET_KEY", required=require_secrets, fallback="test-app-secret"),
        token_encryption_key=_required(
            "TOKEN_ENCRYPTION_KEY", required=require_secrets,
            fallback="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
        ),
        admin_password=_required("ADMIN_PASSWORD", required=require_secrets, fallback="test-password"),
        timezone=os.getenv("TIMEZONE", "Europe/Brussels").strip(),
        report_hour=hour,
        report_minute=minute,
        host=os.getenv("HOST", "0.0.0.0").strip(),
        port=port,
        group_name=os.getenv("GROUP_NAME", "Onze loopgroep").strip(),
        data_dir=data_dir,
        database_path=data_dir / "loopgroep.sqlite3",
        report_dir=data_dir / "reports",
    )
