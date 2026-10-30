from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from maintenance.models import MaintenanceRecord, MaintenancePlan, ReminderLog
from workorders.models import WorkOrder, WorkOrderLine


@transaction.atomic
def record_delivered_work_order(*, work_order, completed_at=None):
    existing = MaintenanceRecord.objects.filter(work_order=work_order).first()
    if existing:
        return existing
    if work_order.status != WorkOrder.Status.DELIVERED:
        raise ValidationError(
            "Solo se registra el historial de una orden entregada."
        )
    lines = work_order.lines.all()
    summary_lines = [
        line.description_snapshot
        for line in lines
    ]
    if work_order.diagnosis.strip():
        summary_lines.insert(0, work_order.diagnosis.strip())
    if not summary_lines:
        summary_lines.append(work_order.complaint.strip())
    return MaintenanceRecord.objects.create(
        motorcycle=work_order.motorcycle,
        work_order=work_order,
        completed_at=completed_at or work_order.closed_at or timezone.now(),
        mileage=work_order.mileage,
        summary="\n".join(summary_lines),
    )


@transaction.atomic
def schedule_reminder(*, plan_id, channel, scheduled_for, actor, note=""):
    if not actor.has_perm("maintenance.reminders.manage"):
        raise ValidationError("No tienes permiso para programar recordatorios.")
    plan = MaintenancePlan.objects.select_for_update().get(pk=plan_id)
    if plan.status != MaintenancePlan.Status.ACTIVE:
        raise ValidationError("Solo se pueden programar recordatorios para planes activos.")
    if channel not in ReminderLog.Channel.values:
        raise ValidationError({"channel": "Canal de recordatorio inválido."})
    try:
        return ReminderLog.objects.create(
            plan=plan,
            channel=channel,
            scheduled_for=scheduled_for,
            created_by=actor,
            note=note.strip(),
        )
    except IntegrityError as exc:
        raise ValidationError(
            "Ya existe un recordatorio de ese canal y fecha para este plan."
        ) from exc


@transaction.atomic
def record_reminder_sent(*, reminder_id, actor, note=""):
    if not actor.has_perm("maintenance.reminders.manage"):
        raise ValidationError("No tienes permiso para registrar envíos.")
    reminder = ReminderLog.objects.select_for_update().get(pk=reminder_id)
    if reminder.status != ReminderLog.Status.PENDING:
        raise ValidationError("Solo se puede registrar como enviado un recordatorio pendiente.")
    reminder.status = ReminderLog.Status.SENT
    reminder.sent_by = actor
    reminder.sent_at = timezone.now()
    if note.strip():
        reminder.note = note.strip()
    reminder.save(
        update_fields=[
            "status",
            "sent_by",
            "sent_at",
            "note",
            "updated_at",
        ]
    )
    return reminder


@transaction.atomic
def update_reminder_status(*, reminder_id, status, actor, note=""):
    if not actor.has_perm("maintenance.reminders.manage"):
        raise ValidationError("No tienes permiso para actualizar recordatorios.")
    reminder = ReminderLog.objects.select_for_update().get(pk=reminder_id)
    if reminder.status != ReminderLog.Status.PENDING:
        raise ValidationError("Solo se puede actualizar un recordatorio pendiente.")
    if status not in {
        ReminderLog.Status.FAILED,
        ReminderLog.Status.CANCELLED,
    }:
        raise ValidationError("Estado de recordatorio inválido.")
    reminder.status = status
    reminder.updated_by = actor
    if note.strip():
        reminder.note = note.strip()
    reminder.save(
        update_fields=["status", "note", "updated_by", "updated_at"]
    )
    return reminder
