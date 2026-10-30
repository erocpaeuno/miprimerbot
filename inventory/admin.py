from django.contrib import admin

from inventory.models import InventoryMovement, Part, Service


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "default_price", "estimated_minutes", "active")
    list_filter = ("active",)
    search_fields = ("name", "description")


@admin.register(Part)
class PartAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "stock", "unit", "unit_price", "active")
    list_filter = ("active",)
    search_fields = ("sku", "name")
    readonly_fields = ("stock",)


@admin.register(InventoryMovement)
class InventoryMovementAdmin(admin.ModelAdmin):
    list_display = (
        "part",
        "work_order",
        "movement_type",
        "quantity",
        "created_by",
        "created_at",
    )
    list_filter = ("movement_type", "created_at")
    search_fields = ("part__sku", "part__name", "note", "created_by__username")
    readonly_fields = (
        "part",
        "work_order",
        "movement_type",
        "quantity",
        "unit_cost",
        "note",
        "created_by",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
