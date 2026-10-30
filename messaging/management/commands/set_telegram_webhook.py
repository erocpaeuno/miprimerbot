import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from messaging.telegram_api import TelegramAPIError, call_telegram


class Command(BaseCommand):
    help = "Registra el webhook HTTPS del bot en Telegram."

    def add_arguments(self, parser):
        parser.add_argument("--url", required=True)

    def handle(self, *args, **options):
        url = options["url"].strip()
        if not url.startswith("https://"):
            raise CommandError("El webhook debe usar HTTPS.")
        if not settings.TELEGRAM_BOT_TOKEN:
            raise CommandError("Define TELEGRAM_BOT_TOKEN antes de registrar el webhook.")
        secret = settings.TELEGRAM_WEBHOOK_SECRET
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret):
            raise CommandError(
                "Define TELEGRAM_WEBHOOK_SECRET con 1–256 caracteres "
                "alfanuméricos, guion o guion bajo."
            )
        try:
            call_telegram(
                "setWebhook",
                {
                    "url": url,
                    "secret_token": secret,
                    "allowed_updates": ["message", "callback_query"],
                },
            )
        except TelegramAPIError as exc:
            raise CommandError(f"No se pudo registrar el webhook: {exc}") from exc
        self.stdout.write(self.style.SUCCESS("Webhook registrado en Telegram."))
