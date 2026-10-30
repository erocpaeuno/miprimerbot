from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from finance.models import CashSession, Expense, Payment
from workorders.models import WorkOrder


def _require_cash_permission(actor):
    if not actor.has_perm("finance.cash.manage"):
        raise PermissionDenied("No tienes permiso para gestionar la caja.")


def _require_session_access(actor, session):
    if session.opened_by_id != actor.pk and not actor.has_perm(
        "finance.cash.override"
    ):
        raise PermissionDenied(
            "Solo quien abrió la caja o administración puede operarla."
        )


def _amount(value, *, field, allow_zero):
    try:
        amount = Decimal(value)
    except (TypeError, ValueError, ArithmeticError) as exc:
        raise ValidationError({field: "El importe no es válido."}) from exc
    if (
        not amount.is_finite()
        or amount < 0
        or (amount == 0 and not allow_zero)
        or amount.as_tuple().exponent < -2
        or amount > Decimal("99999999.99")
    ):
        rule = "no puede ser negativo" if allow_zero else "debe ser mayor que cero"
        raise ValidationError(
            {field: f"El importe {rule} y debe tener hasta dos decimales."}
        )
    return amount.quantize(Decimal("0.01"))


def get_open_session():
    return (
        CashSession.objects.select_related("opened_by")
        .filter(closed_at__isnull=True)
        .first()
    )


@transaction.atomic
def open_cash_session(*, opening_cash, actor):
    _require_cash_permission(actor)
    opening_cash = _amount(
        opening_cash,
        field="opening_cash",
        allow_zero=True,
    )
    if CashSession.objects.select_for_update().filter(
        closed_at__isnull=True
    ).exists():
        raise ValidationError("Ya existe una caja abierta.")
    try:
        return CashSession.objects.create(
            opening_cash=opening_cash,
            opened_by=actor,
        )
    except IntegrityError as exc:
        raise ValidationError("Ya existe una caja abierta.") from exc


def _get_operable_session(*, session_id, actor):
    _require_cash_permission(actor)
    session = CashSession.objects.select_for_update().get(pk=session_id)
    if not session.is_open:
        raise ValidationError("La caja ya está cerrada.")
    _require_session_access(actor, session)
    return session


@transaction.atomic
def record_payment(
    *,
    session_id,
    work_order_id,
    amount,
    method,
    actor,
    note="",
):
    session = _get_operable_session(session_id=session_id, actor=actor)
    amount = _amount(amount, field="amount", allow_zero=False)
    if method not in Payment.Method.values:
        raise ValidationError({"method": "El medio de pago no es válido."})

    work_order = WorkOrder.objects.select_for_update().get(pk=work_order_id)
    if work_order.status not in {
        WorkOrder.Status.READY,
        WorkOrder.Status.DELIVERED,
    }:
        raise ValidationError(
            {"work_order": "Solo se registran pagos de órdenes listas o entregadas."}
        )
    total = work_order.total
    paid = work_order.payments.aggregate(total=Sum("amount"))["total"] or Decimal(
        "0.00"
    )
    balance = total - paid
    if balance <= 0:
        raise ValidationError({"work_order": "La orden ya está pagada."})
    if amount > balance:
        raise ValidationError(
            {"amount": f"El importe supera el saldo pendiente de S/ {balance:.2f}."}
        )
    return Payment.objects.create(
        session=session,
        work_order=work_order,
        amount=amount,
        method=method,
        note=note.strip(),
        created_by=actor,
    )


@transaction.atomic
def record_expense(
    *,
    session_id,
    category,
    description,
    amount,
    method,
    actor,
    reference="",
):
    session = _get_operable_session(session_id=session_id, actor=actor)
    amount = _amount(amount, field="amount", allow_zero=False)
    if category not in Expense.Category.values:
        raise ValidationError({"category": "La categoría no es válida."})
    if method not in Payment.Method.values:
        raise ValidationError({"method": "El medio de pago no es válido."})
    description = description.strip()
    if not description:
        raise ValidationError({"description": "Describe el egreso."})
    if (
        method == Payment.Method.CASH
        and amount > cash_expected_for_session(session)
    ):
        raise ValidationError(
            {"amount": "El egreso supera el efectivo disponible en caja."}
        )
    return Expense.objects.create(
        session=session,
        category=category,
        description=description,
        amount=amount,
        method=method,
        reference=reference.strip(),
        created_by=actor,
    )


def cash_expected_for_session(session):
    cash_payments = (
        session.payments.filter(method=Payment.Method.CASH).aggregate(
            total=Sum("amount")
        )["total"]
        or Decimal("0.00")
    )
    cash_expenses = (
        session.expenses.filter(method=Payment.Method.CASH).aggregate(
            total=Sum("amount")
        )["total"]
        or Decimal("0.00")
    )
    return session.opening_cash + cash_payments - cash_expenses


@transaction.atomic
def close_cash_session(*, session_id, counted_cash, actor):
    session = _get_operable_session(session_id=session_id, actor=actor)
    counted_cash = _amount(
        counted_cash,
        field="counted_cash",
        allow_zero=True,
    )
    expected_cash = cash_expected_for_session(session)
    closed_at = timezone.now()
    CashSession.objects.filter(pk=session.pk, closed_at__isnull=True).update(
        closed_by=actor,
        closed_at=closed_at,
        expected_cash=expected_cash,
        counted_cash=counted_cash,
    )
    session.refresh_from_db()
    return session
