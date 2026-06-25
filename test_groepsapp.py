from __future__ import annotations

import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs

from cryptography.fernet import Fernet

from app import create_app
from config import Settings
from database import (count_participants, get_latest_report, initialise,
                      list_active_participants, save_report, upsert_participant)
from report_service import create_report, format_km, persist_report
from security import TokenCipher


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.settings = Settings(
            client_id="123", client_secret="secret",
            redirect_uri="http://localhost:5000/callback",
            secret_key="test-secret", token_encryption_key=Fernet.generate_key().decode(),
            admin_password="beheer123", timezone="Europe/Brussels",
            report_hour=23, report_minute=59, host="127.0.0.1", port=5000,
            group_name="Testloopgroep", data_dir=base,
            database_path=base / "db.sqlite3", report_dir=base / "reports")
        initialise(self.settings.database_path)
        self.cipher = TokenCipher(self.settings.token_encryption_key)

    def tearDown(self): self.tmp.cleanup()

    def add(self, athlete_id, name):
        first, _, last = name.partition(" ")
        upsert_participant(self.settings.database_path, self.cipher,
            athlete_id=athlete_id, display_name=name, firstname=first,
            lastname=last, access_token=f"access-{athlete_id}",
            refresh_token=f"refresh-{athlete_id}", expires_at=int(time.time())+3600,
            scope="activity:read_all")

    def test_format(self):
        self.assertEqual(format_km(8340), "8,34")
        self.assertEqual(format_km(5000), "5")

    def test_tokens_encrypted_and_decrypted(self):
        self.add(1, "Niels Pepermans")
        raw = self.settings.database_path.read_bytes()
        self.assertNotIn(b"access-1", raw)
        person = list_active_participants(self.settings.database_path, self.cipher)[0]
        self.assertEqual(person["access_token"], "access-1")

    def test_deduplicate_and_omit_inactive_day(self):
        self.add(1, "Niels Pepermans")
        self.add(1, "Niels P.")
        self.add(2, "Jan Janssens")
        self.add(3, "Julie De Smet")
        self.assertEqual(count_participants(self.settings.database_path), 3)
        activities = {
            1:[{"sport_type":"Run","distance":8340,"start_date_local":"2026-06-25T07:00:00"}],
            2:[{"sport_type":"Walk","distance":4700,"start_date_local":"2026-06-25T18:00:00"}],
            3:[]}
        report = create_report(self.settings, date(2026,6,25),
            lambda p,a,b: activities[int(p["athlete_id"])])
        self.assertTrue(report.content.startswith("Stats van vandaag:"))
        self.assertIn("Niels P., 8,34 km", report.content)
        self.assertIn("Jan Janssens, 4,7 km 🚶", report.content)
        self.assertNotIn("Julie", report.content)
        persist_report(self.settings, report)
        self.assertEqual(get_latest_report(self.settings.database_path)["content"], report.content)

    def test_routes_login_and_whatsapp(self):
        save_report(self.settings.database_path, "2026-06-25", "Titel",
                    "Testloopgroep — 25/06/2026\n\nNiels Pepermans, 8,34 km")
        app = create_app(self.settings)
        client = app.test_client()
        self.assertEqual(client.get("/health").status_code, 200)
        response = client.get("/koppelen")
        self.assertEqual(response.status_code, 302)
        self.assertIn("strava.com/oauth/authorize", response.headers["Location"])
        self.assertEqual(client.get("/rapport").status_code, 302)
        login = client.post("/beheer", data={"password":"beheer123"}, follow_redirects=True)
        html = login.get_data(as_text=True)
        self.assertIn("Delen in WhatsApp", html)
        self.assertIn("https://wa.me/?text=", html)
        self.assertIn("Niels Pepermans, 8,34 km", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
