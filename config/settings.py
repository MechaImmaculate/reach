"""Dev settings used to validate the schema. Harden before any pilot."""
import base64, hashlib, os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-not-secret")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
INSTALLED_APPS = [
    "django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions",
    "django.contrib.messages", "django.contrib.admin", "django.contrib.gis", "pgtrigger",
    "apps.core", "apps.accounts", "apps.geo", "apps.facilities", "apps.mothers", "apps.consent",
    "apps.care", "apps.ai", "apps.comms", "apps.triage", "apps.referrals", "apps.appointments",
    "apps.followups", "apps.chw", "apps.spatial", "apps.audit",
]
AUTH_USER_MODEL = "accounts.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "Africa/Nairobi"
ROOT_URLCONF = "config.urls"

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": os.environ.get("POSTGRES_DB", "reach"),
        "USER": os.environ["POSTGRES_USER"],
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

_dev = base64.urlsafe_b64encode(hashlib.sha256(b"reach-dev-field-key").digest()).decode()
REACH_FIELD_KEYS = [k for k in os.environ.get("REACH_FIELD_KEYS", _dev if DEBUG else "").split(",") if k]
REACH_BLIND_INDEX_KEYS = {1: os.environ.get("REACH_BLIND_INDEX_KEY", "dev-blind-index-key").encode()}
REACH_BLIND_INDEX_CURRENT = 1
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True,
  "OPTIONS": {"context_processors": ["django.template.context_processors.request",
  "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages"]}}]
MIDDLEWARE = ["django.contrib.sessions.middleware.SessionMiddleware",
  "django.contrib.auth.middleware.AuthenticationMiddleware",
  "django.contrib.messages.middleware.MessageMiddleware"]
