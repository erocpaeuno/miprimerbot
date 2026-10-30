from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse


class Service(models.Model):
    name = models.CharField("nombre", max_length=120, unique=True)
    description = models.TextField("descripción", blank=True)
    default_price = models.DecimalField(
        "precio referencial",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    estimated_minutes = models.PositiveIntegerField(
        "duración estimada en minutos",
        blank=True,
        null=True,
    )
    active = models.BooleanField("activo", default=True)
    created_at = models.DateTimeField("creado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "servicio"
        verbose_name_plural = "servicios"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("catalog:service_list")


class Part(models.Model):
    sku = models.CharField("código", max_length=40, unique=True)
    name = models.CharField("nombre", max_length=120)
    description = models.TextField("descripción", blank=True)
    unit = models.CharField("unidad", max_length=20, default="unidad")
    unit_price = models.DecimalField(
        "precio de referencia",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    stock = models.DecimalField(
        "existencia",
        max_digits=12,
        decimal_places=3,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    reorder_level = models.DecimalField(
        "nivel de reposición",
        max_digits=12,
        decimal_places=3,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    active = models.BooleanField("activo", default=True)
    created_at = models.DateTimeField("creado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        ordering = ["name", "sku"]
        verbose_name = "repuesto"
        verbose_name_plural = "repuestos"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(stock__gte=0),
                name="part_stock_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(reorder_level__gte=0),
                name="part_reorder_nonnegative",
            ),
        ]
        indexes = [
            models.Index(fields=["active", "name"], name="part_active_name_idx"),
        ]

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def get_absolute_url(self):
        return reverse("inventory:part_detail", args=[self.pk])


class InventoryMovement(models.Model):
    class MovementType(models.TextChoices):
        ENTRY = "entry", "Ingreso"
        EXIT = "exit", "Salida"
        ADJUSTMENT = "adjustment", "Ajuste de conteo"

    part = models.ForeignKey(
        Part,
        on_delete=models.PROTECT,
        related_name="movements",
        verbose_name="repuesto",
    )
    work_order = models.ForeignKey(
        "workorders.WorkOrder",
        on_delete=models.PROTECT,
        related_name="inventory_movements",
        blank=True,
        null=True,
        verbose_name="orden de trabajo",
    )
    movement_type = models.CharField(
        "tipo",
        max_length=12,
        choices=MovementType.choices,
    )
    quantity = models.DecimalField(
        "cantidad",
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="En un ajuste, indica la existencia física contada.",
    )
    unit_cost = models.DecimalField(
        "costo unitario opcional",
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    note = models.CharField("motivo o referencia", max_length=240)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="inventory_movements",
        verbose_name="registrado por",
    )
    created_at = models.DateTimeField("fecha", auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "movimiento de inventario"
        verbose_name_plural = "movimientos de inventario"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(movement_type="adjustment")
                    | models.Q(quantity__gt=0)
                ),
                name="movement_positive_unless_adjustment",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_cost__isnull=True)
                | models.Q(unit_cost__gte=0),
                name="movement_cost_nonnegative",
            ),
        ]
        indexes = [
            models.Index(
                fields=["part", "-created_at"],
                name="movement_part_date_idx",
            ),
        ]

    def __str__(self):
        return f"{self.get_movement_type_display()} — {self.part}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(
                "Los movimientos de inventario son inmutables."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Los movimientos de inventario no se pueden eliminar."
        )
