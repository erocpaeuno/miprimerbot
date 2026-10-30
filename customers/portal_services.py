from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from customers.models import (
    CUSTOMER_PORTAL_CODE_LIFETIME,
    Customer,
    CustomerPortalCode,
    create_customer_portal_code,
    customer_portal_code_digest,
)
from workorders.models import (
    CustomerApproval,
    WorkOrder,
    WorkOrderEvent,
)


@transaction.atomic
def issue_customer_portal_code(*, customer_id, actor):
    if not actor.has_perm("customers.manage_customers"):
        raise PermissionDenied("No tienes permiso para emitir acceso al portal.")
    customer = Customer.objects.get(pk=customer_id)
    now = timezone.now()
    CustomerPortalCode.objects.filter(
        customer=customer,
        used_at__isnull=True,
        expires_at__gt=now,
    ).update(expires_at=now)

    raw_code = create_customer_portal_code()
    CustomerPortalCode.objects.create(
        customer=customer,
        token_digest=customer_portal_code_digest(raw_code),
        issued_by=actor,
        expires_at=now + CUSTOMER_PORTAL_CODE_LIFETIME,
    )
    return raw_code


@transaction.atomic
def consume_customer_portal_code(raw_code):
    if not raw_code or len(raw_code) > 128:
        return None
    code = (
        CustomerPortalCode.objects.select_for_update()
        .filter(
            token_digest=customer_portal_code_digest(raw_code),
            used_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .first()
    )
    if code is None:
        return None
    code.used_at = timezone.now()
    code.save(update_fields=["used_at"])
    return code.customer_id


@transaction.atomic
def respond_to_portal_order(*, work_order_id, customer_id, decision):
    if decision not in {"approve", "reject"}:
        raise ValidationError("La respuesta seleccionada no es válida.")
    work_order = WorkOrder.objects.select_for_update().get(
        pk=work_order_id,
        customer_id=customer_id,
    )
    if work_order.status != WorkOrder.Status.WAITING_APPROVAL:
        raise ValidationError(
            "Esta orden ya no está esperando la aprobación del presupuesto."
        )
    if CustomerApproval.objects.filter(work_order=work_order).exists():
        raise ValidationError("Esta orden ya tiene una aprobación registrada.")

    old_status = work_order.status
    if decision == "approve":
        new_status = WorkOrder.Status.APPROVED
        CustomerApproval.objects.create(
            work_order=work_order,
            channel=CustomerApproval.Channel.PORTAL,
            evidence_note="El cliente aprobó el presupuesto desde el portal.",
            recorded_by=None,
        )
        event_type = WorkOrderEvent.EventType.APPROVAL
        description = "El cliente aprobó el presupuesto desde el portal."
    else:
        new_status = WorkOrder.Status.CANCELLED
        event_type = WorkOrderEvent.EventType.CUSTOMER_REJECTED
        description = "El cliente rechazó el presupuesto desde el portal."

    WorkOrder.objects.filter(pk=work_order.pk).update(
        status=new_status,
        updated_at=timezone.now(),
    )
    WorkOrderEvent.objects.create(
        work_order=work_order,
        event_type=event_type,
        old_status=old_status,
        new_status=new_status,
        actor=None,
        description=description,
    )
    return new_status
