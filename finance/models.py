from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from workorders.models import WorkOrder


class CashSession(models.Model):
    register_number = models.PositiveSmallIntegerField(
        default=1,
        editable=False,
    )
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="opened_cash_sessions",
        verbose_name="abierta por",
    )
    opened_at = models.DateTimeField("apertura", auto_now_add=True)
    opening_cash = models.DecimalField(
        "fondo inicial",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="closed_cash_sessions",
        blank=True,
        null=True,
        verbose_name="cerrada por",
    )
    closed_at = models.DateTimeField("cierre", blank=True, null=True)
    expected_cash = models.DecimalField(
        "efectivo esperado",
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
    )
    counted_cash = models.DecimalField(
        "efectivo contado",
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField("registrada", auto_now_add=True)

    class Meta:
        ordering = ["-opened_at", "-pk"]
        verbose_name = "sesión de caja"
        verbose_name_plural = "sesiones de caja"
        constraints = [
            models.UniqueConstraint(
                fields=["register_number"],
                condition=models.Q(closed_at__isnull=True),
                name="finance_one_open_cash_session",
            ),
            models.CheckConstraint(
                condition=models.Q(opening_cash__gte=0),
                name="finance_opening_cash_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(register_number=1),
                name="finance_single_register_only",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        closed_at__isnull=True,
                        closed_by__isnull=True,
                        expected_cash__isnull=True,
                        counted_cash__isnull=True,
                    )
                    | models.Q(
                        closed_at__isnull=False,
                        closed_by__isnull=False,
                        expected_cash__isnull=False,
                        counted_cash__isnull=False,
                    )
                ),
                name="finance_cash_close_complete",
            ),
        ]

    def __str__(self):
        return f"Caja {self.opened_at:%Y-%m-%d %H:%M}"

    @property
    def is_open(self):
        return self.closed_at is None

    @property
    def difference_cash(self):
        if self.expected_cash is None or self.counted_cash is None:
            return None
        return self.counted_cash - self.expected_cash

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(
                "Las sesiones existentes solo se actualizan desde las acciones de caja."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las sesiones de caja no se pueden eliminar.")


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = "cash", "Efectivo"
        CARD = "card", "Tarjeta"
        TRANSFER = "transfer", "Transferencia"
        YAPE = "yape", "Yape"
        PLIN = "plin", "Plin"

    session = models.ForeignKey(
        CashSession,
        on_delete=models.PROTECT,
        related_name="payments",
        verbose_name="sesión de caja",
    )
    work_order = models.ForeignKey(
        WorkOrder,
        on_delete=models.PROTECT,
        related_name="payments",
        verbose_name="orden de trabajo",
    )
    amount = models.DecimalField(
        "importe",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    method = models.CharField(
        "medio de pago",
        max_length=12,
        choices=Method.choices,
    )
    note = models.CharField("referencia", max_length=180, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_payments",
        verbose_name="registrado por",
    )
    created_at = models.DateTimeField("registrado", auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "pago"
        verbose_name_plural = "pagos"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_payment_positive",
            ),
        ]
        indexes = [
            models.Index(
                fields=["method", "-created_at"],
                name="fin_pay_method_date_idx",
            ),
        ]

    def __str__(self):
        return f"{self.work_order.order_number}: S/ {self.amount}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Los pagos registrados son inmutables.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los pagos registrados no se pueden eliminar.")


class Expense(models.Model):
    class Category(models.TextChoices):
        SUPPLIES = "supplies", "Insumos"
        TRANSPORT = "transport", "Transporte"
        UTILITIES = "utilities", "Servicios"
        MAINTENANCE = "maintenance", "Mantenimiento del taller"
        OTHER = "other", "Otros"

    session = models.ForeignKey(
        CashSession,
        on_delete=models.PROTECT,
        related_name="expenses",
        verbose_name="sesión de caja",
    )
    category = models.CharField(
        "categoría",
        max_length=16,
        choices=Category.choices,
    )
    description = models.CharField("descripción", max_length=180)
    amount = models.DecimalField(
        "importe",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    method = models.CharField(
        "medio de pago",
        max_length=12,
        choices=Payment.Method.choices,
    )
    reference = models.CharField("referencia", max_length=180, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_expenses",
        verbose_name="registrado por",
    )
    created_at = models.DateTimeField("registrado", auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "egreso"
        verbose_name_plural = "egresos"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_expense_positive",
            ),
        ]

    def __str__(self):
        return f"{self.get_category_display()}: S/ {self.amount}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Los egresos registrados son inmutables.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los egresos registrados no se pueden eliminar.")
