# Strava-loopgroep — productieversie

Deze app biedt één algemene Strava-koppellink, maakt dagelijks om 23.59 uur een
rapport en toont voor de beheerder een knop **Delen in WhatsApp**. Personen zonder
loop- of wandelactiviteit worden niet vermeld.

## Railway-instellingen

Gebruik een Railway-service met een persistent volume op `/data` en zet:

```text
DATA_DIR=/data
```

De productie-startopdracht staat reeds in `railway.json` en `Procfile`.
Gebruik één Gunicorn-worker, zodat de dagelijkse scheduler niet dubbel draait.

## Benodigde variabelen

```text
STRAVA_CLIENT_ID=...
STRAVA_CLIENT_SECRET=...
STRAVA_REDIRECT_URI=https://JOUW-DOMEIN/callback
APP_SECRET_KEY=...
TOKEN_ENCRYPTION_KEY=...
ADMIN_PASSWORD=...
TIMEZONE=Europe/Brussels
REPORT_HOUR=23
REPORT_MINUTE=59
GROUP_NAME=Naam van je loopgroep
DATA_DIR=/data
```

Genereer sleutels lokaal:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## URL's

- `/` — publieke startpagina
- `/koppelen` — algemene Strava-koppeling
- `/beheer` — beheerlogin
- `/rapport` — laatste rapport en WhatsApp-knop
- `/rapport/nu` — rapport onmiddellijk opnieuw maken
- `/health` — Railway-healthcheck

## Lokale test

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python test_groepsapp.py
python app.py
```


## Opmaak WhatsApp-bericht

Het gedeelde bericht begint voortaan met:

```text
Stats van vandaag:

Naam loopgroep — 25/06/2026

Niels Pepermans, 8,34 km
Jan Janssens, 4,7 km 🚶
```
