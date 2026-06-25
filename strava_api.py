from __future__ import annotations

import time
from typing import Any

import requests

from config import Settings
from database import update_tokens
from security import TokenCipher

AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
TIMEOUT = 30
REFRESH_MARGIN_SECONDS = 300


class StravaError(RuntimeError):
    pass


def _check(response: requests.Response, action: str) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        try:
            details = response.json()
        except ValueError:
            details = response.text[:500]
        raise StravaError(
            f"Strava-fout tijdens {action}: HTTP {response.status_code}: {details}"
        ) from exc


def exchange_code(settings: Settings, code: str) -> dict[str, Any]:
    response = requests.post(
        TOKEN_URL,
        data={"client_id": settings.client_id,
              "client_secret": settings.client_secret,
              "code": code, "grant_type": "authorization_code"},
        timeout=TIMEOUT,
    )
    _check(response, "het koppelen")
    return response.json()


def refresh_token(settings: Settings, current_refresh_token: str) -> dict[str, Any]:
    response = requests.post(
        TOKEN_URL,
        data={"client_id": settings.client_id,
              "client_secret": settings.client_secret,
              "grant_type": "refresh_token",
              "refresh_token": current_refresh_token},
        timeout=TIMEOUT,
    )
    _check(response, "het vernieuwen van de toegang")
    return response.json()


def valid_access_token(settings: Settings, cipher: TokenCipher, participant: dict) -> str:
    if int(participant["expires_at"]) > int(time.time()) + REFRESH_MARGIN_SECONDS:
        return str(participant["access_token"])
    refreshed = refresh_token(settings, str(participant["refresh_token"]))
    update_tokens(
        settings.database_path, cipher, int(participant["athlete_id"]),
        access_token=str(refreshed["access_token"]),
        refresh_token=str(refreshed["refresh_token"]),
        expires_at=int(refreshed["expires_at"]),
    )
    return str(refreshed["access_token"])


def get_activities(access_token: str, after_epoch: int,
                   before_epoch: int) -> list[dict[str, Any]]:
    headers = {"Authorization": f"Bearer {access_token}"}
    activities: list[dict[str, Any]] = []
    page = 1
    while True:
        response = requests.get(
            ACTIVITIES_URL, headers=headers,
            params={"after": after_epoch, "before": before_epoch,
                    "page": page, "per_page": 200},
            timeout=TIMEOUT,
        )
        _check(response, "het ophalen van activiteiten")
        batch = response.json()
        if not isinstance(batch, list):
            raise StravaError("Strava gaf een onverwacht antwoord terug.")
        if not batch:
            break
        activities.extend(batch)
        page += 1
    return activities
