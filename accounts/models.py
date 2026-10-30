from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models

from accounts.permissions import role_grants


class StaffUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", "administrator")
        return super().create_superuser(
            username,
            email=email,
            password=password,
            **extra_fields,
        )


class StaffUser(AbstractUser):
    class Role(models.TextChoices):
        ADMINISTRATOR = "administrator", "Administrador"
        RECEPTION = "reception", "Recepción"
        TECHNICIAN = "technician", "Técnico"
        CASHIER = "cashier", "Caja"

    role = models.CharField(
        "rol",
        max_length=20,
        choices=Role.choices,
        default=Role.RECEPTION,
    )
    objects = StaffUserManager()

    class Meta:
        verbose_name = "usuario del taller"
        verbose_name_plural = "usuarios del taller"

    def has_perm(self, perm, obj=None):
        if not self.is_active:
            return False
        if self.is_superuser:
            return True
        if obj is None and role_grants(self, perm):
            return True
        return super().has_perm(perm, obj)
