from django.contrib import admin

from customers.models import Customer, Motorcycle


class MotorcycleInline(admin.TabularInline):
    model = Motorcycle
    extra = 0
    readonly_fields = ("plate_normalized",)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("full_name", "phone", "email", "created_at")
    search_fields = ("full_name", "phone", "dni")
    inlines = [MotorcycleInline]


@admin.register(Motorcycle)
class MotorcycleAdmin(admin.ModelAdmin):
    list_display = ("plate", "make", "model", "customer", "current_mileage")
    search_fields = ("plate", "make", "model", "customer__full_name")
    readonly_fields = ("plate_normalized",)
