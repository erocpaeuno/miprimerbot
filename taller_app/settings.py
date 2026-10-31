import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# 1. Definimos primero BASE_DIR para conocer la ubicación raíz del proyecto
BASE_DIR = Path(__file__).resolve().parent.parent

# 2. Apuntamos explícitamente a la ruta absoluta del archivo .env en la raíz
dot_env_path = BASE_DIR / ".env"
if dot_env_path.exists():
    load_dotenv(dotenv_path=dot_env_path)
else:
    load_dotenv()


def env_bool(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default, *, minimum=0, maximum=None):
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} debe ser un número entero.") from exc
    if parsed < minimum or (maximum is not None and parsed > maximum):
        bound = f" entre {minimum} y {maximum}" if maximum is not None else f" mayor o igual a {minimum}"
        raise ImproperlyConfigured(f"{name} debe ser{bound}.")
    return parsed


def postgres_database_from_url(database_url):
    try:
        parsed = urlsplit(database_url)
        name = unquote(parsed.path.lstrip("/"))
        port = parsed.port or 5432
    except ValueError as exc:
        raise ImproperlyConfigured(
            "DATABASE_URL no es una URL de PostgreSQL válida."
        ) from exc
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or not parsed.hostname
        or not name
    ):
        raise ImproperlyConfigured(
            "DATABASE_URL debe apuntar a una base de datos PostgreSQL."
        )
    options = {}
    sslmodes = parse_qs(parsed.query).get("sslmode")
    if sslmodes:
        options["sslmode"] = sslmodes[-1]
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": name,
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname,
        "PORT": str(port),
        "CONN_MAX_AGE": 60,
        "OPTIONS": options,
    }


DEBUG = env_bool("DJANGO_DEBUG", True)
render_hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
if (
    not DEBUG
    and not os.environ.get("DJANGO_ALLOWED_HOSTS", "").strip()
    and not render_hostname
):
    raise ImproperlyConfigured(
        "Define DJANGO_ALLOWED_HOSTS con los dominios públicos del servicio."
    )
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured(
            "Define DJANGO_SECRET_KEY cuando DJANGO_DEBUG no está activado."
        )
    SECRET_KEY = "development-only-not-for-production"

allowed_hosts_setting = os.environ.get("DJANGO_ALLOWED_HOSTS")
ALLOWED_HOSTS = [
    host.strip()
    for host in (
        allowed_hosts_setting or ",".join(["localhost", "127.0.0.1"])
    ).split(",")
    if host.strip()
]
if render_hostname and render_hostname not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(render_hostname)
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
if render_hostname:
    render_origin = f"https://{render_hostname}"
    if render_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(render_origin)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "accounts",
    "customers",
    "inventory",
    "workorders",
    "maintenance",
    "finance",
    "messaging",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "taller_app.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

WSGI_APPLICATION = "taller_app.wsgi.application"
ASGI_APPLICATION = "taller_app.asgi.application"
AUTH_USER_MODEL = "accounts.StaffUser"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:profile"
LOGOUT_REDIRECT_URL = "accounts:login"
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Solución de Escape para la fase de compilación en Render
if not DATABASE_URL and os.environ.get("RENDER"):
    DATABASE_URL = "postgresql://temporal_user:temporal_pass@localhost:5432/temporal_db"

DB_ENGINE = os.environ.get(
    "DB_ENGINE",
    "postgresql" if DATABASE_URL else "sqlite",
).strip().lower()

if DATABASE_URL:
    DATABASES = {"default": postgres_database_from_url(DATABASE_URL)}
elif DB_ENGINE == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "taller_motos"),
            "USER": os.environ.get("DB_USER", ""),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }
elif DB_ENGINE == "sqlite":
    if not DEBUG:
        raise ImproperlyConfigured(
            "SQLite solo está permitido con DEBUG; usa PostgreSQL en producción."
        )
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    raise ImproperlyConfigured(
        "DB_ENGINE debe ser 'sqlite' o 'postgresql'."
    )

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        )
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        )
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        )
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        )
    },
]

LANGUAGE_CODE = "es-pe"
TIME_ZONE = "America/Lima"
USE_I18N = True
USE_TZ = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", not DEBUG)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_HSTS_SECONDS = env_int(
    "DJANGO_SECURE_HSTS_SECONDS",
    0,
    minimum=0,
    maximum=63072000,
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS",
    False,
)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", False)
if env_bool("DJANGO_USE_X_FORWARDED_PROTO", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if not DEBUG and not SECURE_SSL_REDIRECT and not env_bool(
    "DJANGO_USE_X_FORWARDED_PROTO",
    False,
):
    raise ImproperlyConfigured(
        "Activa la redirección HTTPS o configura el proxy TLS confiable."
    )
if not DEBUG and SECURE_HSTS_SECONDS < 1:
    raise ImproperlyConfigured(
        "Define DJANGO_SECURE_HSTS_SECONDS para habilitar HSTS en producción."
    )

CURRENCY_CODE = "PEN"
CURRENCY_SYMBOL = "S/"
try:
    IGV_RATE = Decimal(os.environ.get("IGV_RATE", "0.18"))
except InvalidOperation as exc:
    raise ImproperlyConfigured("IGV_RATE debe ser un value decimal.") from exc
if not IGV_RATE.is_finite() or not Decimal("0") <= IGV_RATE <= Decimal("1"):
    raise ImproperlyConfigured("IGV_RATE debe estar entre 0 y 1.")
