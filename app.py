from __future__ import annotations

import hmac
import logging
import re
from functools import wraps
from urllib.parse import quote, urlencode

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import (Flask, abort, redirect, render_template_string, request,
                   session, url_for)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from config import Settings, get_settings
from database import count_participants, get_latest_report, initialise, upsert_participant
from report_service import run_report
from security import TokenCipher
from strava_api import AUTHORIZE_URL, exchange_code

LOGGER = logging.getLogger(__name__)
STYLE = """
body{font-family:system-ui,-apple-system,sans-serif;max-width:760px;margin:48px auto;padding:0 20px;line-height:1.55;color:#202124}
.card{border:1px solid #ddd;border-radius:16px;padding:24px;box-shadow:0 4px 18px rgba(0,0,0,.06)}
.button{display:inline-block;border:0;border-radius:10px;padding:13px 18px;background:#25D366;color:#fff;text-decoration:none;font-weight:700;cursor:pointer}
.orange{background:#fc4c02}.dark{background:#333}pre{white-space:pre-wrap;background:#f6f7f8;padding:16px;border-radius:10px}
.small{color:#666;font-size:.92rem}input{width:100%;box-sizing:border-box;padding:12px;margin:8px 0 16px;border:1px solid #bbb;border-radius:8px}
"""



def parse_scopes(raw_scope) -> set[str]:
    """Verwerk zowel komma- als spatiegescheiden OAuth-scopes van Strava."""
    if raw_scope is None:
        return set()

    if isinstance(raw_scope, (list, tuple, set)):
        values = raw_scope
    else:
        values = [raw_scope]

    scopes: set[str] = set()
    for value in values:
        scopes.update(
            part for part in re.split(r"[\s,]+", str(value).strip()) if part
        )
    return scopes

def create_app(settings: Settings | None = None) -> Flask:
    cfg = settings or get_settings()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    initialise(cfg.database_path)
    cipher = TokenCipher(cfg.token_encryption_key)
    app = Flask(__name__)
    app.secret_key = cfg.secret_key
    app.config.update(SESSION_COOKIE_SECURE=cfg.redirect_uri.startswith("https://"),
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
    serializer = URLSafeTimedSerializer(cfg.secret_key, salt="strava-loopgroep-oauth")

    def admin_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("admin"):
                return redirect(url_for("beheer", next=request.path))
            return view(*args, **kwargs)
        return wrapped

    @app.get("/health")
    def health():
        return {"status": "ok"}, 200

    @app.get("/")
    def home():
        total = count_participants(cfg.database_path)
        return render_template_string("""<!doctype html><html lang=nl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>{{group}}</title><style>{{style}}</style></head><body><div class=card><h1>{{group}}</h1><p>Koppel je Strava-account éénmalig om in het dagelijkse loop- en wandeloverzicht te worden opgenomen.</p><p><a class='button orange' href='/koppelen'>Koppel mijn Strava</a></p><p class=small>Momenteel gekoppeld: {{total}} deelnemer(s).</p><p><a href='/beheer'>Beheerder</a> · <a href='/privacy'>Privacy</a></p></div></body></html>""", group=cfg.group_name, total=total, style=STYLE)

    @app.get("/privacy")
    def privacy():
        return render_template_string("""<!doctype html><html lang=nl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Privacy</title><style>{{style}}</style></head><body><div class=card><h1>Privacy</h1><p>De toepassing bewaart je Strava-ID, naam en versleutelde toegangstokens om dagelijks je loop- en wandelactiviteiten voor het groepsrapport op te halen.</p><p>De gegevens worden uitsluitend voor dit groepsrapport gebruikt. Je kunt de toegang ook intrekken via je Strava-instellingen onder gekoppelde toepassingen.</p><p><a href='/'>Terug</a></p></div></body></html>""", style=STYLE)

    @app.get("/koppelen")
    def koppelen():
        state = serializer.dumps({"purpose": "group-signup"})
        query = urlencode({"client_id": cfg.client_id, "redirect_uri": cfg.redirect_uri,
                           "response_type": "code", "approval_prompt": "force",
                           "scope": "read,activity:read_all", "state": state})
        return redirect(f"{AUTHORIZE_URL}?{query}")

    @app.get("/callback")
    def callback():
        if request.args.get("error"):
            return "De Strava-koppeling werd geweigerd.", 400
        code, state = request.args.get("code", "").strip(), request.args.get("state", "").strip()
        if not code or not state:
            abort(400, "Code of beveiligingsstatus ontbreekt.")
        try:
            state_data = serializer.loads(state, max_age=900)
        except SignatureExpired:
            abort(400, "De koppellink is verlopen.")
        except BadSignature:
            abort(400, "Ongeldige koppelaanvraag.")
        if state_data.get("purpose") != "group-signup":
            abort(400, "Ongeldige koppelaanvraag.")
        token_data = exchange_code(cfg, code)
        accepted_scopes = (
            parse_scopes(token_data.get("scope"))
            | parse_scopes(request.args.get("scope"))
        )
        if "activity:read_all" not in accepted_scopes:
            abort(
                400,
                "De toestemming om activiteiten te lezen werd niet gegeven. "
                "Vink op het Strava-scherm ook de toegang tot privéactiviteiten aan "
                "en probeer opnieuw.",
            )
        accepted_scope = " ".join(sorted(accepted_scopes))
        athlete = token_data.get("athlete") or {}
        athlete_id = athlete.get("id")
        if athlete_id is None:
            abort(502, "Strava gaf geen sporter-ID terug.")
        firstname, lastname = str(athlete.get("firstname") or "").strip(), str(athlete.get("lastname") or "").strip()
        display_name = " ".join(p for p in (firstname, lastname) if p).strip() or f"Strava-sporter {athlete_id}"
        upsert_participant(cfg.database_path, cipher, athlete_id=int(athlete_id),
                           display_name=display_name, firstname=firstname, lastname=lastname,
                           access_token=str(token_data["access_token"]),
                           refresh_token=str(token_data["refresh_token"]),
                           expires_at=int(token_data["expires_at"]), scope=accepted_scope)
        return render_template_string("""<!doctype html><html lang=nl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Gelukt</title><style>{{style}}</style></head><body><div class=card><h1>Koppeling gelukt</h1><p><strong>{{name}}</strong> is toegevoegd. Je hoeft verder niets te doen.</p><p><a href='/'>Terug</a></p></div></body></html>""", name=display_name, style=STYLE)

    @app.route("/beheer", methods=["GET", "POST"])
    def beheer():
        error = ""
        if request.method == "POST":
            supplied = request.form.get("password", "")
            if hmac.compare_digest(supplied, cfg.admin_password):
                session["admin"] = True
                return redirect(request.args.get("next") or url_for("rapport"))
            error = "Onjuist wachtwoord."
        return render_template_string("""<!doctype html><html lang=nl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Beheer</title><style>{{style}}</style></head><body><div class=card><h1>Beheerder</h1>{% if error %}<p><strong>{{error}}</strong></p>{% endif %}<form method=post><label>Wachtwoord</label><input type=password name=password required><button class='button dark' type=submit>Aanmelden</button></form></div></body></html>""", error=error, style=STYLE)

    @app.get("/uitloggen")
    def uitloggen():
        session.clear()
        return redirect(url_for("home"))

    @app.get("/rapport")
    @admin_required
    def rapport():
        latest = get_latest_report(cfg.database_path)
        content = str(latest["content"]) if latest else f"{cfg.group_name}\n\nEr werd nog geen dagrapport aangemaakt."
        report_date = str(latest["report_date"]) if latest else ""
        whatsapp_url = f"https://wa.me/?text={quote(content, safe='')}"
        return render_template_string("""<!doctype html><html lang=nl><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Dagrapport</title><style>{{style}}</style></head><body><div class=card><h1>Dagrapport</h1>{% if date %}<p class=small>Rapportdatum: {{date}}</p>{% endif %}<pre>{{content}}</pre><p><a class=button href='{{wa}}' target=_blank rel=noopener>Delen in WhatsApp</a></p><p class=small>Kies je bestaande loopgroep en druk op verzenden.</p><p><a href='/rapport/nu'>Rapport nu vernieuwen</a> · <a href='/uitloggen'>Uitloggen</a></p></div></body></html>""", date=report_date, content=content, wa=whatsapp_url, style=STYLE)

    @app.get("/rapport/nu")
    @admin_required
    def rapport_nu():
        run_report(cfg)
        return redirect(url_for("rapport"))

    return app


def start_scheduler(settings: Settings) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=settings.timezone)
    scheduler.add_job(lambda: run_report(settings), CronTrigger(
        hour=settings.report_hour, minute=settings.report_minute,
        timezone=settings.timezone), id="dagelijks-strava-rapport",
        replace_existing=True, coalesce=True, max_instances=1,
        misfire_grace_time=3600)
    scheduler.start()
    LOGGER.info("Scheduler actief: dagelijks om %02d:%02d %s",
                settings.report_hour, settings.report_minute, settings.timezone)
    return scheduler


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = get_settings()
    app = create_app(cfg)
    scheduler = start_scheduler(cfg)
    try:
        app.run(host=cfg.host, port=cfg.port, debug=False, use_reloader=False)
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
