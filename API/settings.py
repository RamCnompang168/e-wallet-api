"""Production-ready settings for the Banking and E-Wallet REST API."""
import os
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv
from corsheaders.defaults import default_headers

BASE_DIR = Path(__file__).resolve().parent.parent

# 1. Load .env file explicitly
load_dotenv(BASE_DIR / ".env", override=True)

# 2. Host Bindings: Allow Android emulator (10.0.2.2) and LAN IP
DEBUG = os.environ.get("DJANGO_DEBUG", "True").lower() == "true"
if DEBUG:
    ALLOWED_HOSTS = ["*"]
else:
    ALLOWED_HOSTS = [
        h.strip()
        for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,10.0.2.2").split(",")
        if h
    ]

# 3. CORS: Allow all origins during dev to avoid Flutter connection rejections
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://10.0.2.2:8000",
    ).split(",")
    if origin
]
CORS_ALLOW_HEADERS = list(default_headers) + [
    "idempotency-key",
    "x-transaction-pin",
]

# 4. Bakong Settings
BAKONG_BASE_URL = os.environ.get("BAKONG_BASE_URL", "https://bakong-open-api-sandbox.nbc.gov.kh").rstrip("/")
BAKONG_API_TOKEN = os.environ.get("BAKONG_API_TOKEN", "")
BAKONG_ACCOUNT_ID = os.environ.get("BAKONG_ACCOUNT_ID", "novapay_sandbox@devb")
BAKONG_MERCHANT_NAME = os.environ.get("BAKONG_MERCHANT_NAME", "NOVAPAY STORE")
BAKONG_MERCHANT_CITY = os.environ.get("BAKONG_MERCHANT_CITY", "PHNOM PENH")
BAKONG_CURRENCY = os.environ.get("BAKONG_DEFAULT_CURRENCY", os.environ.get("BAKONG_CURRENCY", "USD")).upper()
BAKONG_TIMEOUT_SECONDS = int(os.environ.get("BAKONG_TIMEOUT_SECONDS", "15"))

# Security Settings
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-key-change-in-production-min-50-characters-0982348")

JAZZMIN_SETTINGS = {
    "site_title": "NovaPay Admin",
    "site_header": "NovaPay E-Wallet",
    "site_brand": "NovaPay Banking",
    "welcome_sign": "Welcome to NovaPay Management Portal",
    "copyright": "NovaPay Digital Wallet Ltd",
    "search_model": ["users.User", "wallets.Wallet", "transactions.Transaction"],
    "show_sidebar": True,
    "navigation_expanded": True,
    "hide_apps": [],
    "hide_models": [],
    "order_with_respect_to": ["users", "wallets", "transfers", "transactions", "merchants", "payments"],
    "icons": {
        "auth": "fas fa-users-cog",
        "auth.user": "fas fa-user",
        "auth.Group": "fas fa-users",
        "users.User": "fas fa-user-circle",
        "wallets.Wallet": "fas fa-wallet",
        "transfers.Transfer": "fas fa-exchange-alt",
        "transactions.Transaction": "fas fa-file-invoice-dollar",
        "merchants.Merchant": "fas fa-store",
    },
    "default_icon_parents": "fas fa-chevron-circle-right",
    "default_icon_children": "fas fa-circle",
}

# Application Definition
INSTALLED_APPS = [
    "jazzmin",
    # Django Built-in
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-Party Libraries
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt",
    "django_filters",
    "drf_spectacular",
    # Domain Apps
    "apps.core",
    "apps.users",
    "apps.authentication",
    "apps.wallets",
    "apps.transactions",
    "apps.transfers",
    "apps.beneficiaries",
    "apps.payments",
    "apps.merchants",
    "apps.kyc",
    "apps.notifications",
    "apps.settlement",
    "apps.dashboard",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "API.urls"

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

WSGI_APPLICATION = "API.wsgi.application"
ASGI_APPLICATION = "API.asgi.application"

# Database Configuration
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    from urllib.parse import urlparse
    parsed = urlparse(DATABASE_URL)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": parsed.username,
            "PASSWORD": parsed.password,
            "HOST": parsed.hostname,
            "PORT": parsed.port or 5432,
            "CONN_MAX_AGE": 60,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
            "OPTIONS": {
                "timeout": 30,
            },
        }
    }

AUTH_USER_MODEL = "users.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "apps.authentication.permissions.IsActiveUser",
    ),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardResultsSetPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "EXCEPTION_HANDLER": "apps.core.responses.custom_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/minute",
        "user": "600/minute",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.environ.get("JWT_ACCESS_LIFETIME_MINUTES", 15))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(os.environ.get("JWT_REFRESH_LIFETIME_DAYS", 7))),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "NovaPay Banking & Digital Wallet API",
    "DESCRIPTION": (
        "Enterprise-grade REST API for digital wallet and banking operations featuring "
        "double-entry accounting ledger, canonical deadlock-free locking, idempotent mutations, "
        "tiered KYC compliance, dynamic fee management, automated reconciliation, and security audit logs."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/1")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "True").lower() == "true"
CELERY_TASK_EAGER_PROPAGATES = True

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ==============================================================================
# Email Configuration (Real Gmail SMTP / Console fallback)
# ==============================================================================
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", 587))
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "True").lower() == "true"
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "").strip()
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "").replace(" ", "").strip()
DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL",
    f"NovaPay Wallet <{EMAIL_HOST_USER}>" if EMAIL_HOST_USER else "NovaPay Wallet <noreply@novapay.com>"
)
