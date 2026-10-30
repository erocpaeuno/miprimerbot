from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from inventory.models import InventoryMovement, Part, Service
from inventory.services import record_movement
from workorders.models import (
    CustomerApproval,
    WorkOrder,
    WorkOrderEvent,
    WorkOrderLine,
)


ALLOWED_TRANSITIONS = {
    WorkOrder.Status.DRAFT: {
        WorkOrder.Status.RECEIVED,
        WorkOrder.Status.CANCELLED,
    },
    WorkOrder.Status.RECEIVED: {
        WorkOrder.Status.DIAGNOSING,
        WorkOrder.Status.CANCELLED,
    },
    WorkOrder.Status.DIAGNOSING: {
        WorkOrder.Status.WAITING_APPROVAL,
        WorkOrder.Status.CANCELLED,
    },
    WorkOrder.Status.WAITING_APPROVAL: {
        WorkOrder.Status.CANCELLED,
    },
    WorkOrder.Status.APPROVED: {
        WorkOrder.Status.IN_PROGRESS,
        WorkOrder.Status.CANCELLED,
    },
    WorkOrder.Status.IN_PROGRESS: {
        WorkOrder.Status.READY,
    },
    WorkOrder.Status.READY: {
        WorkOrder.Status.DELIVERED,
    },
    WorkOrder.Status.DELIVERED: set(),
    WorkOrder.Status.CANCELLED: set(),
}

TECHNICIAN_TRANSITIONS = {
    (WorkOrder.Status.RECEIVED, WorkOrder.Status.DIAGNOSING),
    (WorkOrder.Status.DIAGNOSING, WorkOrder.Status.WAITING_APPROVAL),
    (WorkOrder.Status.APPROVED, WorkOrder.Status.IN_PROGRESS),
    (WorkOrder.Status.IN_PROGRESS, WorkOrder.Status.READY),
}


def _require_order_access(actor, work_order, *, allow_assigned):
    if actor.has_perm("workorders.manage"):
        return
    if (
        allow_assigned
        and actor.has_perm("workorders.update_assigned")
        and work_order.assigned_to_id == actor.pk
    ):
        return
    raise PermissionDenied("No tienes permiso para modificar esta orden.")


def _consume_part_line(work_order, line, actor):
    if line.stock_deducted or line.line_type != WorkOrderLine.LineType.PART:
        return
    part = Part.objects.get(pk=line.part_id)
    record_movement(
        part_id=part.pk,
        movement_type=InventoryMovement.MovementType.EXIT,
        quantity=line.quantity,
        actor=actor,
        note=f"Consumo {work_order.order_number}: {line.description_snapshot}",
        work_order=work_order,
    )
    WorkOrderLine.objects.filter(pk=line.pk).update(stock_deducted=True)


@transaction.atomic
def create_work_order(*, data, actor):
    if not actor.has_perm("workorders.manage"):
        raise PermissionDenied("No tienes permiso para crear órdenes.")
    if data["motorcycle"].customer_id != data["customer"].pk:
        raise ValidationError(
            {"motorcycle": "La motocicleta no pertenece al cliente seleccionado."}
        )
    assigned_to = data.get("assigned_to")
    if assigned_to and (
        assigned_to.role != "technician" or not assigned_to.is_active
    ):
        raise ValidationError(
            {"assigned_to": "Solo se puede asignar a un técnico activo."}
        )
    if data["mileage"] < data["motorcycle"].current_mileage:
        raise ValidationError(
            {"mileage": "El kilometraje no puede ser menor al último registrado."}
        )
    work_order = WorkOrder.objects.create(
        **data,
        created_by=actor,
        status=WorkOrder.Status.DRAFT,
    )
    WorkOrderEvent.objects.create(
        work_order=work_order,
        event_type=WorkOrderEvent.EventType.CREATED,
        new_status=work_order.status,
        actor=actor,
        description="Orden de trabajo creada.",
    )
    return work_order


@transaction.atomic
def update_work_order(*, work_order_id, data, actor):
    work_order = WorkOrder.objects.select_for_update().get(pk=work_order_id)
    _require_order_access(actor, work_order, allow_assigned=False)
    if work_order.status not in {
        WorkOrder.Status.DRAFT,
        WorkOrder.Status.RECEIVED,
        WorkOrder.Status.DIAGNOSING,
    }:
        raise ValidationError(
            "Los datos generales solo se editan antes de solicitar aprobación."
        )
    changed_fields = [
        field
        for field, value in data.items()
        if getattr(work_order, field) != value
    ]
    for field, value in data.items():
        setattr(work_order, field, value)
    if work_order.motorcycle.customer_id != work_order.customer_id:
        raise ValidationError(
            {"motorcycle": "La motocicleta no pertenece al cliente seleccionado."}
        )
    if work_order.mileage < work_order.motorcycle.current_mileage:
        raise ValidationError(
            {"mileage": "El kilometraje no puede ser menor al último registrado."}
        )
    if work_order.assigned_to and (
        work_order.assigned_to.role != "technician"
        or not work_order.assigned_to.is_active
    ):
        raise ValidationError(
            {"assigned_to": "Solo se puede asignar a un técnico activo."}
        )
    work_order.save()
    if changed_fields:
        WorkOrderEvent.objects.create(
            work_order=work_order,
            event_type=WorkOrderEvent.EventType.DETAILS_UPDATED,
            old_status=work_order.status,
            new_status=work_order.status,
            actor=actor,
            description=(
                "Datos actualizados: " + ", ".join(changed_fields) + "."
            ),
        )
    return work_order


@transaction.atomic
def transition_work_order(*, work_order_id, new_status, actor):
    work_order = WorkOrder.objects.select_for_update().get(pk=work_order_id)
    _require_order_access(actor, work_order, allow_assigned=True)

    if new_status == WorkOrder.Status.APPROVED:
        raise ValidationError(
            "Registra la aprobación del cliente mediante la acción de aprobación."
        )
    if new_status not in ALLOWED_TRANSITIONS.get(work_order.status, set()):
        raise ValidationError("La transición solicitada no está permitida.")
    if new_status == WorkOrder.Status.WAITING_APPROVAL:
        if not work_order.diagnosis.strip():
            raise ValidationError(
                "Registra el diagnóstico antes de solicitar aprobación."
            )
        if not work_order.lines.exists():
            raise ValidationError(
                "Añade al menos un servicio o repuesto al presupuesto."
            )
    if actor.has_perm("workorders.update_assigned") and not actor.has_perm(
        "workorders.manage"
    ):
        if work_order.assigned_to_id != actor.pk or (
            work_order.status,
            new_status,
        ) not in TECHNICIAN_TRANSITIONS:
            raise PermissionDenied(
                "El técnico asignado no puede realizar esta transición."
            )

    if new_status == WorkOrder.Status.IN_PROGRESS:
        for line in work_order.lines.select_for_update().filter(
            line_type=WorkOrderLine.LineType.PART,
            stock_deducted=False,
        ):
            _consume_part_line(work_order, line, actor)

    old_status = work_order.status
    update_fields = {"status": new_status, "updated_at": timezone.now()}
    if new_status == WorkOrder.Status.DELIVERED:
        update_fields["closed_at"] = timezone.now()
    WorkOrder.objects.filter(pk=work_order.pk).update(**update_fields)
    if new_status == WorkOrder.Status.DELIVERED:
        motorcycle = work_order.motorcycle
        if work_order.mileage > motorcycle.current_mileage:
            motorcycle.current_mileage = work_order.mileage
            motorcycle.save(update_fields=["current_mileage", "updated_at"])
        from maintenance.services import record_delivered_work_order

        work_order.refresh_from_db()
        record_delivered_work_order(work_order=work_order)
    WorkOrderEvent.objects.create(
        work_order=work_order,
        event_type=WorkOrderEvent.EventType.TRANSITION,
        old_status=old_status,
        new_status=new_status,
        actor=actor,
        description=(
            f"Estado cambiado de {work_order.get_status_display()} a "
            f"{WorkOrder.Status(new_status).label}."
        ),
    )
    if new_status in {
        WorkOrder.Status.WAITING_APPROVAL,
        WorkOrder.Status.READY,
    }:
        from messaging.services import enqueue_order_message

        message_type = (
            "approval_request"
            if new_status == WorkOrder.Status.WAITING_APPROVAL
            else "work_ready"
        )
        enqueue_order_message(
            work_order_id=work_order.pk,
            message_type=message_type,
        )
    work_order.refresh_from_db()
    return work_order


@transaction.atomic
def approve_work_order(*, work_order_id, channel, evidence_note, actor):
    if not actor.has_perm("workorders.approve"):
        raise PermissionDenied("No tienes permiso para registrar aprobaciones.")
    work_order = WorkOrder.objects.select_for_update().get(pk=work_order_id)
    if work_order.status != WorkOrder.Status.WAITING_APPROVAL:
        raise ValidationError(
            "Solo se puede aprobar una orden que espera aprobación."
        )
    evidence_note = evidence_note.strip()
    if not evidence_note:
        raise ValidationError(
            {"evidence_note": "Describe la confirmación recibida del cliente."}
        )
    if channel not in CustomerApproval.Channel.values:
        raise ValidationError({"channel": "Medio de aprobación inválido."})

    approval = CustomerApproval.objects.create(
        work_order=work_order,
        channel=channel,
        evidence_note=evidence_note,
        recorded_by=actor,
    )
    old_status = work_order.status
    WorkOrder.objects.filter(pk=work_order.pk).update(
        status=WorkOrder.Status.APPROVED,
        updated_at=timezone.now(),
    )
    WorkOrderEvent.objects.create(
        work_order=work_order,
        event_type=WorkOrderEvent.EventType.APPROVAL,
        old_status=old_status,
        new_status=WorkOrder.Status.APPROVED,
        actor=actor,
        description=(
            f"Aprobación registrada por {approval.get_channel_display()}."
        ),
    )
    work_order.refresh_from_db()
    return work_order


@transaction.atomic
def add_work_order_line(
    *,
    work_order_id,
    line_type,
    item_id,
    quantity,
    actor,
):
    work_order = WorkOrder.objects.select_for_update().get(pk=work_order_id)
    _require_order_access(actor, work_order, allow_assigned=True)
    if work_order.status not in {
        WorkOrder.Status.DRAFT,
        WorkOrder.Status.RECEIVED,
        WorkOrder.Status.DIAGNOSING,
        WorkOrder.Status.IN_PROGRESS,
    }:
        raise ValidationError("No se pueden añadir líneas en este estado.")
    if actor.has_perm("workorders.update_assigned") and not actor.has_perm(
        "workorders.manage"
    ):
        if (
            work_order.assigned_to_id != actor.pk
            or work_order.status
            not in {
                WorkOrder.Status.DIAGNOSING,
                WorkOrder.Status.IN_PROGRESS,
            }
        ):
            raise PermissionDenied(
                "Solo puedes actualizar líneas de una orden asignada en trabajo."
            )

    quantity = Decimal(quantity)
    if not quantity.is_finite() or quantity <= 0:
        raise ValidationError({"quantity": "La cantidad debe ser mayor que cero."})

    line_data = {
        "work_order": work_order,
        "line_type": line_type,
        "quantity": quantity,
    }
    if line_type == WorkOrderLine.LineType.SERVICE:
        service = Service.objects.get(pk=item_id, active=True)
        line_data.update(
            service=service,
            description_snapshot=service.name,
            unit_price=service.default_price,
        )
    elif line_type == WorkOrderLine.LineType.PART:
        part = Part.objects.select_for_update().get(pk=item_id, active=True)
        line_data.update(
            part=part,
            description_snapshot=f"{part.name} ({part.sku})",
            unit_price=part.unit_price,
        )
    else:
        raise ValidationError({"line_type": "Tipo de línea inválido."})

    line = WorkOrderLine.objects.create(**line_data)
    if (
        line.line_type == WorkOrderLine.LineType.PART
        and work_order.status == WorkOrder.Status.IN_PROGRESS
    ):
        _consume_part_line(work_order, line, actor)
        line.refresh_from_db()

    WorkOrderEvent.objects.create(
        work_order=work_order,
        event_type=WorkOrderEvent.EventType.LINE_ADDED,
        old_status=work_order.status,
        new_status=work_order.status,
        actor=actor,
        description=(
            f"Línea añadida: {line.description_snapshot}, "
            f"{line.quantity} x S/ {line.unit_price}."
        ),
    )
    return line


@transaction.atomic
def remove_work_order_line(*, work_order_id, line_id, actor):
    line = WorkOrderLine.objects.select_for_update().select_related(
        "work_order"
    ).get(pk=line_id, work_order_id=work_order_id)
    work_order = WorkOrder.objects.select_for_update().get(
        pk=line.work_order_id
    )
    _require_order_access(actor, work_order, allow_assigned=True)
    if work_order.status not in {
        WorkOrder.Status.DRAFT,
        WorkOrder.Status.RECEIVED,
        WorkOrder.Status.DIAGNOSING,
    }:
        raise ValidationError(
            "Las líneas no se pueden retirar después de aprobar el presupuesto."
        )
    if actor.has_perm("workorders.update_assigned") and not actor.has_perm(
        "workorders.manage"
    ):
        if (
            work_order.assigned_to_id != actor.pk
            or work_order.status != WorkOrder.Status.DIAGNOSING
        ):
            raise PermissionDenied(
                "Solo puedes retirar líneas durante el diagnóstico de una orden asignada."
            )
    if line.stock_deducted:
        raise ValidationError(
            "No se puede retirar una línea cuyo repuesto ya se descontó."
        )

    WorkOrderEvent.objects.create(
        work_order=work_order,
        event_type=WorkOrderEvent.EventType.LINE_REMOVED,
        old_status=work_order.status,
        new_status=work_order.status,
        actor=actor,
        description=(
            f"Línea retirada: {line.description_snapshot}, "
            f"{line.quantity} x S/ {line.unit_price}."
        ),
    )
    WorkOrderLine.objects.filter(pk=line.pk).delete()


@transaction.atomic
def update_assigned_work(*, work_order_id, diagnosis, notes, actor):
    work_order = WorkOrder.objects.select_for_update().get(pk=work_order_id)
    _require_order_access(actor, work_order, allow_assigned=True)
    if actor.has_perm("workorders.manage"):
        raise ValidationError(
            "El personal de administración debe usar la edición general."
        )
    if work_order.status not in {
        WorkOrder.Status.DIAGNOSING,
        WorkOrder.Status.IN_PROGRESS,
    }:
        raise ValidationError(
            "El diagnóstico solo se actualiza durante diagnóstico o trabajo."
        )
    old_diagnosis = work_order.diagnosis
    old_notes = work_order.notes
    work_order.diagnosis = diagnosis
    work_order.notes = notes
    work_order.save(update_fields=["diagnosis", "notes", "updated_at"])
    if old_diagnosis != diagnosis or old_notes != notes:
        WorkOrderEvent.objects.create(
            work_order=work_order,
            event_type=WorkOrderEvent.EventType.DETAILS_UPDATED,
            old_status=work_order.status,
            new_status=work_order.status,
            actor=actor,
            description="El técnico actualizó el diagnóstico o las notas.",
        )
    return work_order
