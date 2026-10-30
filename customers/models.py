import hashlib
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Customer(models.Model):
    full_name = models.CharField("nombre completo", max_length=160)
    dni = models.CharField(
        "DNI",
        max_length=8,
        unique=True,
        blank=True,
        null=True,
        validators=[
            RegexValidator(
                regex=r"^\d{8}$",
                message="El DNI debe contener exactamente 8 dígitos.",
            )
        ],
        help_text="Opcional. Dato personal visible solo al personal autorizado.",
    )
    phone = models.CharField("teléfono", max_length=30, db_index=True)
    email = models.EmailField("correo electrónico", blank=True)
    notes = models.TextField("notas", blank=True)
    created_at = models.DateTimeField("registrado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        ordering = ["full_name", "id"]
        verbose_name = "cliente"
        verbose_name_plural = "clientes"

    def __str__(self):
        return self.full_name

    def get_absolute_url(self):
        return reverse("customers:customer_detail", args=[self.pk])


class Motorcycle(models.Model):
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="motorcycles",
        verbose_name="cliente propietario",
    )
    plate = models.CharField("placa o código", max_length=20)
    plate_normalized = models.CharField(
        "placa normalizada",
        max_length=20,
        unique=True,
        editable=False,
    )
    make = models.CharField("marca", max_length=80)
    model = models.CharField("modelo", max_length=80)
    year = models.PositiveSmallIntegerField(
        "año",
        blank=True,
        null=True,
        validators=[
            MinValueValidator(1900),
            MaxValueValidator(2100),
        ],
    )
    motorcycle_type = models.CharField(
        "tipo",
        max_length=60,
        blank=True,
        help_text="Por ejemplo: scooter, urbana o deportiva.",
    )
    current_mileage = models.PositiveIntegerField(
        "kilometraje actual",
        default=0,
        validators=[MinValueValidator(0)],
    )
    created_at = models.DateTimeField("registrada", auto_now_add=True)
    updated_at = models.DateTimeField("actualizada", auto_now=True)

    class Meta:
        ordering = ["plate", "id"]
        verbose_name = "motocicleta"
        verbose_name_plural = "motocicletas"
        indexes = [
            models.Index(fields=["make", "model"], name="moto_make_model_idx"),
        ]

    def __str__(self):
        return f"{self.plate} — {self.make} {self.model}"

    def save(self, *args, **kwargs):
        self.plate = re.sub(r"\s+", " ", self.plate.strip()).upper()
        self.plate_normalized = re.sub(r"[^A-Z0-9]", "", self.plate)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("customers:motorcycle_detail", args=[self.pk])


class CustomerPortalCode(models.Model):
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="portal_codes",
        verbose_name="cliente",
    )
    token_digest = models.CharField(max_length=64, unique=True, editable=False)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="issued_customer_portal_codes",
        verbose_name="emitido por",
    )
    created_at = models.DateTimeField("emitido", auto_now_add=True)
    expires_at = models.DateTimeField("vence")
    used_at = models.DateTimeField("utilizado", blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "código de acceso al portal del cliente"
        verbose_name_plural = "códigos de acceso al portal del cliente"
        indexes = [
            models.Index(
                fields=["customer", "expires_at"],
                name="customer_portal_exp_idx",
            ),
        ]

    def __str__(self):
        return f"Código de portal para {self.customer}"


def create_customer_portal_code():
    return secrets.token_urlsafe(24)


def customer_portal_code_digest(raw_code):
    return hashlib.sha256(raw_code.encode("utf-8")).hexdigest()


CUSTOMER_PORTAL_CODE_LIFETIME = timedelta(minutes=15)
