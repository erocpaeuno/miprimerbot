from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from accounts.models import StaffUser


@admin.register(StaffUser)
class StaffUserAdmin(UserAdmin):
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "role",
        "is_active",
    )
    list_filter = ("role", "is_active", "is_staff")
    fieldsets = UserAdmin.fieldsets + (
        ("Taller", {"fields": ("role",)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Taller", {"fields": ("role",)}),
    )
