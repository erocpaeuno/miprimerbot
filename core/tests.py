from decimal import Decimal

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from taller_app.settings import postgres_database_from_url


class HealthEndpointTests(TestCase):
    def test_root_returns_service_status(self):
        response = self.client.get(reverse("health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"service": "taller-motos", "status": "ok"},
        )

    def test_confirmed_workshop_defaults_are_configured(self):
        self.assertEqual(settings.LANGUAGE_CODE, "es-pe")
        self.assertEqual(settings.TIME_ZONE, "America/Lima")
        self.assertEqual(settings.CURRENCY_CODE, "PEN")
        self.assertEqual(settings.CURRENCY_SYMBOL, "S/")
        self.assertEqual(settings.IGV_RATE, Decimal("0.18"))

    def test_security_and_static_defaults_are_configured(self):
        self.assertTrue(settings.SECURE_CONTENT_TYPE_NOSNIFF)
        self.assertEqual(settings.SECURE_REFERRER_POLICY, "same-origin")
        self.assertEqual(settings.SECURE_CROSS_ORIGIN_OPENER_POLICY, "same-origin")
        self.assertEqual(settings.STATIC_ROOT.name, "staticfiles")
        self.assertIsNotNone(finders.find("core/app.css"))

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_ssl_redirect_can_be_enabled_for_production(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 301)
        self.assertTrue(response["Location"].startswith("https://"))

    def test_profile_page_uses_shared_responsive_stylesheet(self):
        from accounts.models import StaffUser

        user = StaffUser.objects.create_user(
            username="recepcion",
            role=StaffUser.Role.RECEPTION,
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, "/static/core/app.css")

    def test_postgres_database_url_is_parsed_without_exposing_credentials(self):
        config = postgres_database_from_url(
            "postgresql://taller:password%40encoded@db.example.pe:5432/taller"
            "?sslmode=require"
        )

        self.assertEqual(config["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(config["NAME"], "taller")
        self.assertEqual(config["USER"], "taller")
        self.assertEqual(config["PASSWORD"], "password@encoded")
        self.assertEqual(config["HOST"], "db.example.pe")
        self.assertEqual(config["OPTIONS"], {"sslmode": "require"})

    def test_database_url_rejects_non_postgresql_schemes(self):
        with self.assertRaises(ImproperlyConfigured):
            postgres_database_from_url("sqlite:///db.sqlite3")
