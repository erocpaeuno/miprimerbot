from decimal import Decimal, ROUND_HALF_UP
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse

from customers.models import Customer, Motorcycle
from inventory.models import Part, Service


class WorkOrder(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        RECEIVED = "received", "Recibida"
        DIAGNOSING = "diagnosing", "Diagnosticando"
        WAITING_APPROVAL = "waiting_approval", "Esperando aprobación"
        APPROVED = "approved", "Aprobada"
        IN_PROGRESS = "in_progress", "En proceso"
        READY = "ready", "Lista"
        DELIVERED = "delivered", "Entregada"
        CANCELLED = "cancelled", "Cancelada"

    order_number = models.CharField(
        "número de orden",
        max_length=16,
        unique=True,
        blank=True,
        editable=False,
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="work_orders",
        verbose_name="cliente",
    )
    motorcycle = models.ForeignKey(
        Motorcycle,
        on_delete=models.PROTECT,
        related_name="work_orders",
        verbose_name="motocicleta",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_work_orders",
        blank=True,
        null=True,
        verbose_name="técnico asignado",
    )
    status = models.CharField(
        "estado",
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    opened_at = models.DateTimeField("fecha de apertura", auto_now_add=True)
    closed_at = models.DateTimeField("fecha de entrega", blank=True, null=True)
    mileage = models.PositiveIntegerField(
        "kilometraje al recibir",
        validators=[MinValueValidator(0)],
    )
    complaint = models.TextField("motivo de ingreso")
    diagnosis = models.TextField("diagnóstico", blank=True)
    notes = models.TextField("notas internas", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_work_orders",
        verbose_name="registrada por",
    )
    created_at = models.DateTimeField("creada", auto_now_add=True)
    updated_at = models.DateTimeField("actualizada", auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "orden de trabajo"
        verbose_name_plural = "órdenes de trabajo"
        indexes = [
            models.Index(
                fields=["status", "-created_at"],
                name="workorder_status_date_idx",
            ),
            models.Index(
                fields=["assigned_to", "status"],
                name="workorder_assignee_status_idx",
            ),
        ]

    def __str__(self):
        return self.order_number

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.only("status").get(pk=self.pk)
            if previous.status != self.status:
                raise ValidationError(
                    "Cambia el estado mediante las acciones de la orden."
                )
        if not self.order_number:
            self.order_number = f"OT-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    @property
    def total(self):
        return sum(
            (line.line_total for line in self.lines.all()),
            start=Decimal("0.00"),
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def can_change_lines(self):
        return self.status in {
            self.Status.DRAFT,
            self.Status.RECEIVED,
            self.Status.DIAGNOSING,
            self.Status.IN_PROGRESS,
        }

    def get_absolute_url(self):
        return reverse("workorders:detail", args=[self.pk])


class WorkOrderLine(models.Model):
    class LineType(models.TextChoices):
        SERVICE = "service", "Servicio"
        PART = "part", "Repuesto"

    work_order = models.ForeignKey(
        WorkOrder,
        on_delete=models.PROTECT,
        related_name="lines",
        verbose_name="orden de trabajo",
    )
    line_type = models.CharField(
        "tipo",
        max_length=10,
        choices=LineType.choices,
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.PROTECT,
        related_name="work_order_lines",
        blank=True,
        null=True,
        verbose_name="servicio del catálogo",
    )
    part = models.ForeignKey(
        Part,
        on_delete=models.PROTECT,
        related_name="work_order_lines",
        blank=True,
        null=True,
        verbose_name="repuesto del inventario",
    )
    description_snapshot = models.CharField(
        "descripción al registrar",
        max_length=180,
    )
    quantity = models.DecimalField(
        "cantidad",
        max_digits=10,
        decimal_places=3,
        validators=[MinValueValidator(0)],
    )
    unit_price = models.DecimalField(
        "precio unitario acordado",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    stock_deducted = models.BooleanField(
        "descontado del inventario",
        default=False,
    )
    created_at = models.DateTimeField("registrado", auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "línea de orden"
        verbose_name_plural = "líneas de orden"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(line_type="service", service__isnull=False, part__isnull=True)
                    | models.Q(line_type="part", part__isnull=False, service__isnull=True)
                ),
                name="workorder_line_one_catalog_item",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="workorder_line_quantity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name="workorder_line_price_nonnegative",
            ),
        ]

    def __str__(self):
        return self.description_snapshot

    @property
    def line_total(self):
        return (self.quantity * self.unit_price).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(
                "Las líneas se conservan como fotografía histórica; registra "
                "una nueva línea para corregir el presupuesto."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Las líneas de la orden no se pueden eliminar."
        )


class WorkOrderEvent(models.Model):
    class EventType(models.TextChoices):
        CREATED = "created", "Orden creada"
        TRANSITION = "transition", "Cambio de estado"
        APPROVAL = "approval", "Aprobación registrada"
        CUSTOMER_REJECTED = "customer_rejected", "Presupuesto rechazado"
        LINE_ADDED = "line_added", "Línea añadida"
        LINE_REMOVED = "line_removed", "Línea retirada"
        DETAILS_UPDATED = "details_updated", "Diagnóstico actualizado"

    work_order = models.ForeignKey(
        WorkOrder,
        on_delete=models.PROTECT,
        related_name="events",
        verbose_name="orden",
    )
    event_type = models.CharField("evento", max_length=20, choices=EventType.choices)
    old_status = models.CharField(
        "estado anterior",
        max_length=20,
        blank=True,
    )
    new_status = models.CharField(
        "estado nuevo",
        max_length=20,
        blank=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="work_order_events",
        blank=True,
        null=True,
        verbose_name="usuario",
    )
    description = models.CharField("detalle", max_length=300, blank=True)
    created_at = models.DateTimeField("fecha", auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
        verbose_name = "evento de orden"
        verbose_name_plural = "eventos de órdenes"

    def __str__(self):
        return f"{self.work_order} — {self.get_event_type_display()}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("El historial de órdenes es inmutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("El historial de órdenes no se puede eliminar.")


class CustomerApproval(models.Model):
    class Channel(models.TextChoices):
        IN_PERSON = "in_person", "Presencial"
        PHONE = "phone", "Teléfono"
        TELEGRAM_MANUAL = (
            "telegram_manual",
            "Telegram (registrado manualmente)",
        )
        TELEGRAM = "telegram", "Telegram"
        PORTAL = "portal", "Portal del cliente"
        OTHER = "other", "Otro medio"

    work_order = models.OneToOneField(
        WorkOrder,
        on_delete=models.PROTECT,
        related_name="customer_approval",
        verbose_name="orden",
    )
    channel = models.CharField(
        "medio de aprobación",
        max_length=20,
        choices=Channel.choices,
    )
    evidence_note = models.CharField(
        "detalle de la confirmación recibida",
        max_length=300,
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_customer_approvals",
        blank=True,
        null=True,
        verbose_name="registrada por",
    )
    approved_at = models.DateTimeField("fecha de aprobación", auto_now_add=True)

    class Meta:
        verbose_name = "aprobación del cliente"
        verbose_name_plural = "aprobaciones de clientes"

    def __str__(self):
        return f"Aprobación de {self.work_order}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("La aprobación registrada es inmutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("La aprobación registrada no se puede eliminar.")
