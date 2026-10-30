from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from customers.models import Customer
from workorders.models import WorkOrder


class TelegramAccount(models.Model):
    customer = models.OneToOneField(
        Customer,
        on_delete=models.PROTECT,
        related_name="telegram_account",
        verbose_name="cliente",
    )
    chat_id = models.BigIntegerField("chat de Telegram", unique=True)
    is_active = models.BooleanField("vinculación activa", default=True)
    work_updates_consent = models.BooleanField(
        "consiente avisos sobre sus trabajos",
        default=False,
    )
    offers_consent = models.BooleanField(
        "consiente recibir ofertas",
        default=False,
    )
    work_updates_consent_at = models.DateTimeField(blank=True, null=True)
    offers_consent_at = models.DateTimeField(blank=True, null=True)
    linked_at = models.DateTimeField("vinculada", default=timezone.now)
    updated_at = models.DateTimeField("actualizada", auto_now=True)

    class Meta:
        verbose_name = "cuenta de Telegram"
        verbose_name_plural = "cuentas de Telegram"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(work_updates_consent=True, work_updates_consent_at__isnull=False)
                    | Q(work_updates_consent=False, work_updates_consent_at__isnull=True)
                ),
                name="msg_work_consent_timestamp",
            ),
            models.CheckConstraint(
                condition=(
                    Q(offers_consent=True, offers_consent_at__isnull=False)
                    | Q(offers_consent=False, offers_consent_at__isnull=True)
                ),
                name="msg_offer_consent_timestamp",
            ),
        ]

    def __str__(self):
        return f"Telegram de {self.customer}"


class TelegramConsentEvent(models.Model):
    class Category(models.TextChoices):
        WORK_UPDATES = "work_updates", "Avisos de trabajos"
        OFFERS = "offers", "Ofertas"

    account = models.ForeignKey(
        TelegramAccount,
        on_delete=models.PROTECT,
        related_name="consent_events",
    )
    category = models.CharField(max_length=16, choices=Category.choices)
    granted = models.BooleanField()
    update = models.ForeignKey(
        "messaging.TelegramUpdate",
        on_delete=models.PROTECT,
        related_name="consent_events",
    )
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at", "-pk"]
        verbose_name = "cambio de consentimiento de Telegram"
        verbose_name_plural = "cambios de consentimiento de Telegram"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("El historial de consentimiento es inmutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("El historial de consentimiento no se puede eliminar.")


class TelegramLinkToken(models.Model):
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="telegram_link_tokens",
        verbose_name="cliente",
    )
    token_digest = models.CharField(max_length=64, unique=True, editable=False)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="issued_telegram_link_tokens",
        verbose_name="emitido por",
    )
    created_at = models.DateTimeField("emitido", auto_now_add=True)
    expires_at = models.DateTimeField("vence")
    used_at = models.DateTimeField("utilizado", blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "código de vinculación de Telegram"
        verbose_name_plural = "códigos de vinculación de Telegram"
        indexes = [
            models.Index(
                fields=["customer", "expires_at"],
                name="msg_link_customer_exp_idx",
            ),
        ]

    def __str__(self):
        return f"Código Telegram para {self.customer}"


class TelegramUpdate(models.Model):
    update_id = models.BigIntegerField(unique=True)
    update_type = models.CharField(max_length=24)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at"]
        verbose_name = "actualización recibida de Telegram"
        verbose_name_plural = "actualizaciones recibidas de Telegram"


class TelegramOrderResponse(models.Model):
    class Decision(models.TextChoices):
        APPROVED = "approved", "Aprobado"
        REJECTED = "rejected", "Rechazado"

    work_order = models.OneToOneField(
        WorkOrder,
        on_delete=models.PROTECT,
        related_name="telegram_response",
        verbose_name="orden de trabajo",
    )
    update = models.OneToOneField(
        TelegramUpdate,
        on_delete=models.PROTECT,
        related_name="order_response",
        verbose_name="actualización de Telegram",
    )
    decision = models.CharField(max_length=10, choices=Decision.choices)
    responded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "respuesta de aprobación por Telegram"
        verbose_name_plural = "respuestas de aprobación por Telegram"

    def __str__(self):
        return f"{self.work_order}: {self.get_decision_display()}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Las respuestas de Telegram son inmutables.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las respuestas de Telegram no se pueden eliminar.")


class TelegramOutbox(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        SENDING = "sending", "En proceso"
        SENT = "sent", "Enviado"
        FAILED = "failed", "Fallido"
        CANCELLED = "cancelled", "Cancelado"

    event_key = models.CharField(max_length=180, unique=True)
    account = models.ForeignKey(
        TelegramAccount,
        on_delete=models.PROTECT,
        related_name="outgoing_messages",
        blank=True,
        null=True,
    )
    work_order = models.ForeignKey(
        WorkOrder,
        on_delete=models.PROTECT,
        related_name="telegram_outbox_messages",
        blank=True,
        null=True,
    )
    chat_id = models.BigIntegerField()
    message_type = models.CharField(max_length=24)
    method = models.CharField(max_length=32, default="sendMessage")
    payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    processing_at = models.DateTimeField(blank=True, null=True)
    last_error = models.CharField(max_length=300, blank=True)
    telegram_message_id = models.BigIntegerField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["created_at", "pk"]
        verbose_name = "mensaje saliente de Telegram"
        verbose_name_plural = "mensajes salientes de Telegram"
        indexes = [
            models.Index(
                fields=["status", "created_at"],
                name="msg_outbox_status_date_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(attempts__lte=255),
                name="msg_outbox_attempts_max",
            ),
        ]

    def __str__(self):
        return f"{self.message_type} ({self.get_status_display()})"


class OfferCampaign(models.Model):
    message = models.CharField("mensaje de la oferta", max_length=900)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="telegram_offer_campaigns",
        verbose_name="creada por",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "campaña de ofertas"
        verbose_name_plural = "campañas de ofertas"

    def __str__(self):
        return f"Oferta del {self.created_at:%Y-%m-%d}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Las campañas registradas son inmutables.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las campañas registradas no se pueden eliminar.")
