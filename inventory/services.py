from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from inventory.models import InventoryMovement, Part


@transaction.atomic
def record_movement(
    *,
    part_id,
    movement_type,
    quantity,
    actor,
    note,
    unit_cost=None,
    work_order=None,
):
    if movement_type not in InventoryMovement.MovementType.values:
        raise ValidationError({"movement_type": "Tipo de movimiento inválido."})
    quantity = Decimal(quantity)
    if not quantity.is_finite() or quantity < 0:
        raise ValidationError({"quantity": "La cantidad no es válida."})
    if movement_type != InventoryMovement.MovementType.ADJUSTMENT and quantity <= 0:
        raise ValidationError(
            {"quantity": "El ingreso o la salida debe ser mayor que cero."}
        )
    if not note.strip():
        raise ValidationError({"note": "Indica el motivo del movimiento."})
    if unit_cost is not None:
        unit_cost = Decimal(unit_cost)
        if not unit_cost.is_finite() or unit_cost < 0:
            raise ValidationError({"unit_cost": "El costo unitario no es válido."})

    part = Part.objects.select_for_update().get(pk=part_id)
    if movement_type == InventoryMovement.MovementType.ENTRY:
        new_stock = part.stock + quantity
    elif movement_type == InventoryMovement.MovementType.EXIT:
        new_stock = part.stock - quantity
        if new_stock < 0:
            raise ValidationError(
                {"quantity": "No hay existencias suficientes para esa salida."}
            )
    else:
        new_stock = quantity

    movement = InventoryMovement.objects.create(
        part=part,
        work_order=work_order,
        movement_type=movement_type,
        quantity=quantity,
        unit_cost=unit_cost,
        note=note.strip(),
        created_by=actor,
    )
    part.stock = new_stock
    part.save(update_fields=["stock", "updated_at"])
    return movement
