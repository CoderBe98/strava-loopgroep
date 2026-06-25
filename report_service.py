from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from config import Settings
from database import list_active_participants, save_report
from security import TokenCipher
from strava_api import get_activities, valid_access_token

LOGGER = logging.getLogger(__name__)
RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}
WALK_TYPES = {"Walk", "Hike"}


@dataclass(frozen=True)
class GeneratedReport:
    report_date: date
    title: str
    content: str
    errors: tuple[str, ...]


def format_km(distance_metres: float) -> str:
    value = f"{max(float(distance_metres), 0.0) / 1000.0:.2f}".rstrip("0").rstrip(".")
    return value.replace(".", ",")


def day_bounds(target_date: date, timezone_name: str) -> tuple[int, int]:
    tz = ZoneInfo(timezone_name)
    start = datetime.combine(target_date, time.min, tzinfo=tz)
    end = datetime.combine(target_date + timedelta(days=1), time.min, tzinfo=tz)
    return int(start.timestamp()), int(end.timestamp())


def activity_kind(activity: dict) -> str:
    return str(activity.get("sport_type") or activity.get("type") or "")



def report_intro(chosen_date: date, current_date: date) -> str:
    if chosen_date == current_date:
        return "Stats van vandaag:"
    if chosen_date == current_date - timedelta(days=1):
        return "Stats van gisteren:"
    return f"Stats van {chosen_date.strftime('%d/%m/%Y')}:"

def create_report(settings: Settings, target_date: date | None = None,
                  activity_provider: Callable[[dict, int, int], list[dict]] | None = None) -> GeneratedReport:
    cipher = TokenCipher(settings.token_encryption_key)
    timezone = ZoneInfo(settings.timezone)
    chosen_date = target_date or datetime.now(timezone).date()
    after_epoch, before_epoch = day_bounds(chosen_date, settings.timezone)
    participants = list_active_participants(settings.database_path, cipher)
    lines: list[tuple[str, str, str]] = []
    errors: list[str] = []

    def official_provider(participant: dict, after: int, before: int) -> list[dict]:
        token = valid_access_token(settings, cipher, participant)
        return get_activities(token, after, before)

    provider = activity_provider or official_provider
    for participant in participants:
        name = str(participant["display_name"])
        try:
            activities = provider(participant, after_epoch, before_epoch)
        except Exception as exc:
            LOGGER.exception("Kon activiteiten voor %s niet ophalen.", name)
            errors.append(f"{name}: {exc}")
            continue
        for activity in activities:
            kind = activity_kind(activity)
            if kind not in RUN_TYPES and kind not in WALK_TYPES:
                continue
            icon = " 🚶" if kind in WALK_TYPES else ""
            text = f"{name}, {format_km(float(activity.get('distance') or 0.0))} km{icon}"
            start = str(activity.get("start_date_local") or activity.get("start_date") or "")
            lines.append((name.casefold(), start, text))

    lines.sort(key=lambda item: (item[0], item[1]))
    current_date = datetime.now(timezone).date()
    title = f"{settings.group_name} — {chosen_date.strftime('%d/%m/%Y')}"
    if lines:
        body = "\n".join(item[2] for item in lines)
    elif chosen_date == current_date:
        body = "Geen loop- of wandelactiviteiten vandaag."
    else:
        body = "Geen loop- of wandelactiviteiten op deze datum."
    content = f"{report_intro(chosen_date, current_date)}\n\n{title}\n\n{body}"
    return GeneratedReport(chosen_date, title, content, tuple(errors))


def persist_report(settings: Settings, report: GeneratedReport) -> Path:
    save_report(settings.database_path, report.report_date.isoformat(), report.title, report.content)
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    output = settings.report_dir / f"{report.report_date.isoformat()}.txt"
    output.write_text(report.content + "\n", encoding="utf-8")
    return output


def run_report(settings: Settings, target_date: date | None = None) -> GeneratedReport:
    report = create_report(settings, target_date)
    output = persist_report(settings, report)
    LOGGER.info("Rapport opgeslagen als %s", output)
    if report.errors:
        LOGGER.warning("Niet verwerkte deelnemers: %s", "; ".join(report.errors))
    return report
