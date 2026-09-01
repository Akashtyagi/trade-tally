"""Django settings for Trade Tally."""

import json
import os
import sys
from pathlib import Path

from django.contrib.messages import constants as message_constants
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

TESTING = "pytest" in sys.modules or os.environ.get("TESTING") == "1"

SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-dev-only-change-me")
DEBUG = os.getenv("DEBUG", "true").lower() in {"1", "true", "yes"}
ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "trades",
    "integrations",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

_db_engine = os.getenv("DB_ENGINE", "django.db.backends.mysql")
if TESTING:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }
elif _db_engine.endswith("sqlite3"):
    DATABASES = {
        "default": {
            "ENGINE": _db_engine,
            "NAME": os.getenv("DB_NAME", str(BASE_DIR / "db.sqlite3")),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": _db_engine,
            "NAME": os.getenv("DB_NAME", "trade_tally"),
            "USER": os.getenv("DB_USER", "trade_tally"),
            "PASSWORD": os.getenv("DB_PASSWORD", "trade_tally"),
            "HOST": os.getenv("DB_HOST", "127.0.0.1"),
            "PORT": os.getenv("DB_PORT", "3306"),
            "OPTIONS": {
                "charset": "utf8mb4",
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

MESSAGE_TAGS = {message_constants.ERROR: "danger"}

CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.getenv("CSRF_TRUSTED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")
    if o.strip()
]

# Kite Connect placeholders
KITE_API_KEY = os.getenv("KITE_API_KEY", "your_api_key_here")
KITE_API_SECRET = os.getenv("KITE_API_SECRET", "your_api_secret_here")
KITE_API_BASE_URL = os.getenv("KITE_API_BASE_URL", "https://api.kite.trade")
KITE_REDIRECT_URL = os.getenv("KITE_REDIRECT_URL", "http://127.0.0.1:8000/kite/callback/")

# Google Sheets
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_FILE", str(BASE_DIR / "google-credentials.json")
)
GOOGLE_SHEETS_SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
GOOGLE_SHEETS_WORKSHEET = os.getenv("GOOGLE_SHEETS_WORKSHEET", "Trades")
_default_column_map = {
    "symbol": "symbol",
    "exchange": "exchange",
    "qty": "qty",
    "buy_low": "buy_low",
    "buy_high": "buy_high",
    "target": "target",
    "stop_loss": "stop_loss",
    "status": "status",
    "closed_qty": "closed_qty",
    "closed_price": "closed_price",
    "notes": "notes",
}
try:
    SHEET_COLUMN_MAP = {**_default_column_map, **json.loads(os.getenv("SHEET_COLUMN_MAP", "{}"))}
except json.JSONDecodeError:
    SHEET_COLUMN_MAP = _default_column_map

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "your_telegram_bot_token_here")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Scheduler / cron
ENABLE_SCHEDULER = os.getenv("ENABLE_SCHEDULER", "false").lower() in {"1", "true", "yes"}
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "5"))
CRON_SECRET = os.getenv("CRON_SECRET", "change-me-cron-secret")
MARKET_OPEN = os.getenv("MARKET_OPEN", "09:15")
MARKET_CLOSE = os.getenv("MARKET_CLOSE", "15:30")
