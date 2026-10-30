from django.core.management.base import BaseCommand, CommandError

from messaging.models import TelegramOutbox


class Command(BaseCommand):
    help = "Reencola manualmente un mensaje de Telegram fallido."

    def add_arguments(self, parser):
        parser.add_argument("--message-id", required=True, type=int)

    def handle(self, *args, **options):
        message = TelegramOutbox.objects.filter(
            pk=options["message_id"],
            status=TelegramOutbox.Status.FAILED,
        ).first()
        if not message:
            raise CommandError("No existe un mensaje fallido con ese ID.")
        TelegramOutbox.objects.filter(pk=message.pk).update(
            status=TelegramOutbox.Status.PENDING,
            attempts=0,
            processing_at=None,
            last_error="",
        )
        self.stdout.write(
            self.style.SUCCESS(f"Mensaje {message.pk} reencolado.")
        )
