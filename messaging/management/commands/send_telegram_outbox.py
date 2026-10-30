from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from messaging.models import TelegramOutbox
from messaging.services import (
    can_deliver_message,
    cancel_message,
    mark_message_failed,
    mark_message_sent,
)
from messaging.telegram_api import TelegramAPIError, call_telegram


class Command(BaseCommand):
    help = "Envía mensajes pendientes a Telegram y registra el resultado."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument(
            "--retry-failed",
            action="store_true",
            help="Reintenta fallos con menos de cinco intentos.",
        )

    def handle(self, *args, **options):
        if not settings.TELEGRAM_BOT_TOKEN:
            raise CommandError("Define TELEGRAM_BOT_TOKEN antes de enviar mensajes.")
        limit = options["limit"]
        if limit < 1 or limit > 1000:
            raise CommandError("--limit debe estar entre 1 y 1000.")
        now = timezone.now()
        TelegramOutbox.objects.filter(
            status=TelegramOutbox.Status.SENDING,
            processing_at__lt=now - timedelta(minutes=10),
        ).update(
            status=TelegramOutbox.Status.PENDING,
            processing_at=None,
        )
        if options["retry_failed"]:
            TelegramOutbox.objects.filter(
                status=TelegramOutbox.Status.FAILED,
                attempts__lt=5,
            ).update(
                status=TelegramOutbox.Status.PENDING,
                last_error="",
            )

        message_ids = list(
            TelegramOutbox.objects.filter(
                status=TelegramOutbox.Status.PENDING,
                attempts__lt=5,
            )
            .order_by("created_at", "pk")
            .values_list("pk", flat=True)[:limit]
        )
        sent = failed = cancelled = 0
        for message_id in message_ids:
            claimed = TelegramOutbox.objects.filter(
                pk=message_id,
                status=TelegramOutbox.Status.PENDING,
            ).update(
                status=TelegramOutbox.Status.SENDING,
                processing_at=timezone.now(),
            )
            if not claimed:
                continue
            message = TelegramOutbox.objects.select_related("account").get(
                pk=message_id
            )
            if not can_deliver_message(message):
                cancel_message(message=message)
                cancelled += 1
                continue
            try:
                result = call_telegram(message.method, message.payload)
            except TelegramAPIError as exc:
                mark_message_failed(message=message, error=exc)
                self.stderr.write(
                    self.style.ERROR(f"Mensaje {message.pk}: {exc}")
                )
                failed += 1
                continue
            telegram_message_id = (
                result.get("message_id")
                if isinstance(result, dict)
                else None
            )
            mark_message_sent(
                message=message,
                telegram_message_id=telegram_message_id,
            )
            sent += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Telegram: {sent} enviado(s), {failed} fallido(s), "
                f"{cancelled} cancelado(s)."
            )
        )
