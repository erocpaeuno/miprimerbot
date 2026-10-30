from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from maintenance.forms import (
    MaintenancePlanForm,
    MarkReminderSentForm,
    ReminderForm,
    ReminderStatusForm,
)
from maintenance.models import MaintenancePlan, MaintenanceRecord, ReminderLog
from maintenance.services import (
    record_reminder_sent,
    schedule_reminder,
    update_reminder_status,
)


def _require_permission(user, permission):
    if not user.has_perm(permission):
        raise PermissionDenied


@login_required
def index(request):
    _require_permission(request.user, "maintenance.view")
    plans = MaintenancePlan.objects.select_related(
        "motorcycle",
        "motorcycle__customer",
        "created_by",
    )
    if not request.user.has_perm("maintenance.manage"):
        plans = plans.filter(status=MaintenancePlan.Status.ACTIVE)
    plans = list(plans)
    history = MaintenanceRecord.objects.select_related(
        "motorcycle",
        "motorcycle__customer",
        "work_order",
    )[:50]
    return render(
        request,
        "maintenance/index.html",
        {
            "plans": plans,
            "due_plans": [plan for plan in plans if plan.is_due],
            "history": history,
            "can_manage": request.user.has_perm("maintenance.manage"),
            "today": timezone.localdate(),
        },
    )


@login_required
def plan_create(request):
    _require_permission(request.user, "maintenance.manage")
    form = MaintenancePlanForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        plan = form.save(actor=request.user)
        messages.success(request, "Plan de mantenimiento registrado.")
        return redirect(plan)
    return render(
        request,
        "maintenance/plan_form.html",
        {"form": form, "title": "Programar mantenimiento"},
    )


@login_required
def plan_update(request, pk):
    _require_permission(request.user, "maintenance.manage")
    plan = get_object_or_404(MaintenancePlan, pk=pk)
    form = MaintenancePlanForm(
        request.POST or None,
        instance=plan,
    )
    if request.method == "POST" and form.is_valid():
        form.save(actor=request.user)
        messages.success(request, "Plan de mantenimiento actualizado.")
        return redirect(plan)
    return render(
        request,
        "maintenance/plan_form.html",
        {"form": form, "title": f"Editar {plan.service_name}"},
    )


@login_required
def plan_detail(request, pk):
    _require_permission(request.user, "maintenance.view")
    plan = get_object_or_404(
        MaintenancePlan.objects.select_related(
            "motorcycle",
            "motorcycle__customer",
            "created_by",
        ).prefetch_related("reminders__created_by", "reminders__sent_by"),
        pk=pk,
    )
    if (
        plan.status != MaintenancePlan.Status.ACTIVE
        and not request.user.has_perm("maintenance.manage")
    ):
        raise PermissionDenied
    reminder_form = (
        ReminderForm(plan=plan)
        if request.user.has_perm("maintenance.reminders.manage")
        and plan.status == MaintenancePlan.Status.ACTIVE
        else None
    )
    return render(
        request,
        "maintenance/plan_detail.html",
        {
            "plan": plan,
            "records": plan.motorcycle.maintenance_records.select_related(
                "work_order"
            ),
            "reminder_form": reminder_form,
            "can_manage": request.user.has_perm("maintenance.manage"),
            "can_manage_reminders": request.user.has_perm(
                "maintenance.reminders.manage"
            ),
            "can_view_reminder_details": request.user.has_perm(
                "maintenance.reminders.manage"
            ),
            "today": timezone.localdate(),
        },
    )


@login_required
def reminder_create(request, pk):
    _require_permission(request.user, "maintenance.reminders.manage")
    plan = get_object_or_404(MaintenancePlan, pk=pk)
    if request.method != "POST":
        raise PermissionDenied
    form = ReminderForm(request.POST, plan=plan)
    if form.is_valid():
        try:
            schedule_reminder(
                plan_id=plan.pk,
                actor=request.user,
                **form.cleaned_data,
            )
        except ValidationError as error:
            if hasattr(error, "message_dict"):
                for field, errors in error.message_dict.items():
                    for message in errors:
                        form.add_error(
                            field if field in form.fields else None,
                            message,
                        )
            else:
                form.add_error(None, error)
        else:
            messages.success(
                request,
                "Recordatorio registrado. No se envió ningún mensaje.",
            )
            return redirect(plan)
    return render(
        request,
        "maintenance/plan_detail.html",
        {
            "plan": plan,
            "records": plan.motorcycle.maintenance_records.select_related(
                "work_order"
            ),
            "reminder_form": form,
            "can_manage": request.user.has_perm("maintenance.manage"),
            "can_manage_reminders": True,
            "can_view_reminder_details": True,
            "today": timezone.localdate(),
        },
    )


@login_required
def reminder_mark_sent(request, pk):
    _require_permission(request.user, "maintenance.reminders.manage")
    reminder = get_object_or_404(
        ReminderLog.objects.select_related("plan"),
        pk=pk,
    )
    if request.method != "POST":
        raise PermissionDenied
    form = MarkReminderSentForm(request.POST)
    if form.is_valid():
        try:
            record_reminder_sent(
                reminder_id=reminder.pk,
                actor=request.user,
                **form.cleaned_data,
            )
        except ValidationError as error:
            messages.error(request, "; ".join(error.messages))
        else:
            messages.success(
                request,
                "El envío quedó registrado manualmente; la aplicación no envió el mensaje.",
            )
    else:
        messages.error(request, "Debes anotar la constancia del envío manual.")
    return redirect(reminder.plan)


@login_required
def reminder_update_status(request, pk):
    _require_permission(request.user, "maintenance.reminders.manage")
    reminder = get_object_or_404(
        ReminderLog.objects.select_related("plan"),
        pk=pk,
    )
    if request.method != "POST":
        raise PermissionDenied
    form = ReminderStatusForm(request.POST)
    if form.is_valid():
        try:
            update_reminder_status(
                reminder_id=reminder.pk,
                actor=request.user,
                **form.cleaned_data,
            )
        except ValidationError as error:
            messages.error(request, "; ".join(error.messages))
        else:
            messages.success(request, "Estado del recordatorio actualizado.")
    else:
        messages.error(request, "El estado del recordatorio no es válido.")
    return redirect(reminder.plan)
