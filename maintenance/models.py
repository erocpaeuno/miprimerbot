from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from customers.models import Motorcycle


class MaintenanceRecord(models.Model):
    motorcycle = models.ForeignKey(
        Motorcycle,
        on_delete=models.PROTECT,
        related_name="maintenance_records",
        verbose_name="motocicleta",
    )
    work_order = models.OneToOneField(
        "workorders.WorkOrder",
        on_delete=models.PROTECT,
        related_name="maintenance_record",
        verbose_name="orden entregada",
    )
    completed_at = models.DateTimeField("servicio completado")
    mileage = models.PositiveIntegerField(
        "kilometraje del servicio",
        validators=[MinValueValidator(0)],
    )
    summary = models.TextField("trabajos realizados")
    created_at = models.DateTimeField("registro creado", auto_now_add=True)

    class Meta:
        ordering = ["-completed_at", "-pk"]
        verbose_name = "registro de mantenimiento"
        verbose_name_plural = "historial de mantenimiento"
        indexes = [
            models.Index(
                fields=["motorcycle", "-completed_at"],
                name="maint_record_bike_date_idx",
            ),
        ]

    def __str__(self):
        return f"{self.motorcycle} — {self.completed_at:%Y-%m-%d}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("El historial de mantenimiento es inmutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("El historial de mantenimiento no se puede borrar.")


class MaintenancePlan(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Activo"
        COMPLETED = "completed", "Completado"
        CANCELLED = "cancelled", "Cancelado"

    motorcycle = models.ForeignKey(
        Motorcycle,
        on_delete=models.PROTECT,
        related_name="maintenance_plans",
        verbose_name="motocicleta",
    )
    service_name = models.CharField("mantenimiento previsto", max_length=120)
    last_completed_at = models.DateField(
        "último servicio (fecha)",
        blank=True,
        null=True,
    )
    last_completed_mileage = models.PositiveIntegerField(
        "último servicio (kilometraje)",
        blank=True,
        null=True,
        validators=[MinValueValidator(0)],
    )
    due_date = models.DateField(
        "próxima fecha prevista",
        blank=True,
        null=True,
        db_index=True,
    )
    due_mileage = models.PositiveIntegerField(
        "próximo kilometraje previsto",
        blank=True,
        null=True,
        validators=[MinValueValidator(0)],
    )
    status = models.CharField(
        "estado",
        max_length=12,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )
    notes = models.CharField("notas", max_length=300, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_maintenance_plans",
        verbose_name="programado por",
    )
    created_at = models.DateTimeField("creado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        ordering = ["status", "due_date", "due_mileage", "motorcycle__plate"]
        verbose_name = "plan de mantenimiento"
        verbose_name_plural = "planes de mantenimiento"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(due_date__isnull=False)
                    | models.Q(due_mileage__isnull=False)
                ),
                name="maint_plan_has_due_threshold",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(last_completed_mileage__isnull=True)
                    | models.Q(due_mileage__isnull=True)
                    | models.Q(due_mileage__gt=models.F("last_completed_mileage"))
                ),
                name="maint_due_mileage_after_last",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "due_date"],
                name="maint_plan_status_date_idx",
            ),
        ]

    def __str__(self):
        return f"{self.motorcycle} — {self.service_name}"

    @property
    def is_due(self):
        if self.status != self.Status.ACTIVE:
            return False
        return self.date_is_due or self.mileage_is_due

    @property
    def date_is_due(self):
        return (
            self.status == self.Status.ACTIVE
            and self.due_date is not None
            and self.due_date <= timezone.localdate()
        )

    @property
    def mileage_is_due(self):
        return (
            self.status == self.Status.ACTIVE
            and self.due_mileage is not None
            and self.motorcycle.current_mileage >= self.due_mileage
        )

    def get_absolute_url(self):
        return reverse("maintenance:plan_detail", args=[self.pk])


class ReminderLog(models.Model):
    class Channel(models.TextChoices):
        TELEGRAM = "telegram", "Telegram (registro manual; envío automático pendiente)"
        PHONE = "phone", "Llamada telefónica"
        IN_PERSON = "in_person", "Atención presencial"

    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        SENT = "sent", "Enviado (registrado manualmente)"
        FAILED = "failed", "Fallido"
        CANCELLED = "cancelled", "Cancelado"

    plan = models.ForeignKey(
        MaintenancePlan,
        on_delete=models.PROTECT,
        related_name="reminders",
        verbose_name="plan",
    )
    channel = models.CharField(
        "canal",
        max_length=12,
        choices=Channel.choices,
        default=Channel.TELEGRAM,
    )
    scheduled_for = models.DateField("fecha programada")
    status = models.CharField(
        "estado",
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    note = models.CharField("detalle", max_length=300, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_maintenance_reminders",
        verbose_name="programado por",
    )
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sent_maintenance_reminders",
        blank=True,
        null=True,
        verbose_name="envío registrado por",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_maintenance_reminders",
        blank=True,
        null=True,
        verbose_name="última actualización por",
    )
    sent_at = models.DateTimeField("fecha de envío", blank=True, null=True)
    created_at = models.DateTimeField("creado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        ordering = ["scheduled_for", "id"]
        verbose_name = "registro de recordatorio"
        verbose_name_plural = "registros de recordatorios"
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "channel", "scheduled_for"],
                name="maint_reminder_unique_schedule",
            ),
        ]

    def __str__(self):
        return f"{self.plan} — {self.scheduled_for}"

    def clean(self):
        if self.status == self.Status.SENT and (
            not self.sent_at or not self.sent_by_id
        ):
            raise ValidationError(
                "Un envío registrado requiere usuario y fecha de envío."
            )

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.get(pk=self.pk)
            if original.status == self.Status.SENT:
                raise ValidationError(
                    "Un recordatorio enviado es inmutable; programa uno nuevo "
                    "si hace falta."
                )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los registros de recordatorio no se pueden borrar.")
