from django.contrib import admin

from maintenance.models import MaintenancePlan, MaintenanceRecord, ReminderLog


@admin.register(MaintenanceRecord)
class MaintenanceRecordAdmin(admin.ModelAdmin):
    list_display = ("motorcycle", "work_order", "completed_at", "mileage")
    list_filter = ("completed_at",)
    search_fields = ("motorcycle__plate", "work_order__order_number", "summary")
    readonly_fields = (
        "motorcycle",
        "work_order",
        "completed_at",
        "mileage",
        "summary",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in {"GET", "HEAD"} and super().has_change_permission(
            request, obj
        )

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MaintenancePlan)
class MaintenancePlanAdmin(admin.ModelAdmin):
    list_display = (
        "motorcycle",
        "service_name",
        "due_date",
        "due_mileage",
        "status",
        "created_by",
    )
    list_filter = ("status", "due_date")
    search_fields = ("motorcycle__plate", "service_name")


@admin.register(ReminderLog)
class ReminderLogAdmin(admin.ModelAdmin):
    list_display = (
        "plan",
        "channel",
        "scheduled_for",
        "status",
        "sent_at",
        "created_by",
    )
    list_filter = ("status", "channel", "scheduled_for")
    search_fields = ("plan__service_name", "plan__motorcycle__plate", "note")
    readonly_fields = (
        "plan",
        "channel",
        "scheduled_for",
        "status",
        "note",
        "created_by",
        "sent_by",
        "updated_by",
        "sent_at",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in {"GET", "HEAD"} and super().has_change_permission(
            request, obj
        )

    def has_delete_permission(self, request, obj=None):
        return False
