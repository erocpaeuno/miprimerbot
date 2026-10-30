from django.contrib import admin

from workorders.models import (
    CustomerApproval,
    WorkOrder,
    WorkOrderEvent,
    WorkOrderLine,
)


class WorkOrderLineInline(admin.TabularInline):
    model = WorkOrderLine
    extra = 0
    can_delete = False
    readonly_fields = (
        "line_type",
        "service",
        "part",
        "description_snapshot",
        "quantity",
        "unit_price",
        "stock_deducted",
        "created_at",
    )

    def has_add_permission(self, request, obj=None):
        return False


class WorkOrderEventInline(admin.TabularInline):
    model = WorkOrderEvent
    extra = 0
    can_delete = False
    readonly_fields = (
        "event_type",
        "old_status",
        "new_status",
        "actor",
        "description",
        "created_at",
    )

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_number",
        "customer",
        "motorcycle",
        "status",
        "assigned_to",
        "opened_at",
    )
    list_filter = ("status", "opened_at")
    search_fields = (
        "order_number",
        "customer__full_name",
        "motorcycle__plate",
    )
    readonly_fields = (
        "order_number",
        "customer",
        "motorcycle",
        "assigned_to",
        "status",
        "mileage",
        "complaint",
        "diagnosis",
        "notes",
        "opened_at",
        "closed_at",
        "created_by",
        "created_at",
        "updated_at",
    )
    inlines = [WorkOrderLineInline, WorkOrderEventInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in {"GET", "HEAD"} and super().has_change_permission(
            request, obj
        )

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CustomerApproval)
class CustomerApprovalAdmin(admin.ModelAdmin):
    list_display = ("work_order", "channel", "recorded_by", "approved_at")
    readonly_fields = (
        "work_order",
        "channel",
        "evidence_note",
        "recorded_by",
        "approved_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in {"GET", "HEAD"} and super().has_change_permission(
            request, obj
        )

    def has_delete_permission(self, request, obj=None):
        return False
