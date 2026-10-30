from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.utils import timezone

from finance.forms import (
    CloseCashForm,
    ExpenseForm,
    OpenCashForm,
    PaymentForm,
    ReportFilterForm,
)
from finance.models import CashSession, Expense, Payment
from finance.services import (
    cash_expected_for_session,
    close_cash_session,
    get_open_session,
    open_cash_session,
    record_expense,
    record_payment,
)


def _require_permission(user, permission):
    if not user.has_perm(permission):
        raise PermissionDenied


def _add_validation_error(form, error):
    if hasattr(error, "message_dict"):
        for field, errors in error.message_dict.items():
            for message in errors:
                form.add_error(field if field in form.fields else None, message)
    else:
        form.add_error(None, error)


def _sessions_list():
    return CashSession.objects.select_related("opened_by", "closed_by")[:10]


@login_required
def index(request):
    _require_permission(request.user, "finance.cash.manage")
    session = get_open_session()
    can_operate = bool(
        session
        and (
            session.opened_by_id == request.user.pk
            or request.user.has_perm("finance.cash.override")
        )
    )
    return render(
        request,
        "finance/index.html",
        {
            "session": session,
            "can_operate": can_operate,
            "open_form": OpenCashForm() if not session else None,
            "payment_form": PaymentForm() if can_operate else None,
            "expense_form": ExpenseForm() if can_operate else None,
            "close_form": CloseCashForm() if can_operate else None,
            "expected_cash": (
                cash_expected_for_session(session) if can_operate else None
            ),
            "sessions": _sessions_list(),
        },
    )


@login_required
def cash_open(request):
    _require_permission(request.user, "finance.cash.manage")
    if request.method != "POST":
        raise PermissionDenied
    form = OpenCashForm(request.POST)
    if form.is_valid():
        try:
            open_cash_session(actor=request.user, **form.cleaned_data)
        except ValidationError as error:
            _add_validation_error(form, error)
        else:
            messages.success(request, "Caja abierta.")
            return redirect("finance:index")
    return render(
        request,
        "finance/index.html",
        {
            "session": get_open_session(),
            "can_operate": False,
            "open_form": form,
            "sessions": _sessions_list(),
        },
    )


@login_required
def payment_create(request):
    _require_permission(request.user, "finance.cash.manage")
    if request.method != "POST":
        raise PermissionDenied
    session = get_open_session()
    if not session:
        messages.error(request, "Abre la caja antes de registrar un pago.")
        return redirect("finance:index")
    form = PaymentForm(request.POST)
    if form.is_valid():
        try:
            record_payment(
                session_id=session.pk,
                actor=request.user,
                **form.cleaned_data,
            )
        except ValidationError as error:
            _add_validation_error(form, error)
        else:
            messages.success(request, "Pago registrado.")
            return redirect("finance:index")
    return _render_open_session_with_form(
        request,
        session,
        payment_form=form,
    )


@login_required
def expense_create(request):
    _require_permission(request.user, "finance.cash.manage")
    if request.method != "POST":
        raise PermissionDenied
    session = get_open_session()
    if not session:
        messages.error(request, "Abre la caja antes de registrar un egreso.")
        return redirect("finance:index")
    form = ExpenseForm(request.POST)
    if form.is_valid():
        try:
            record_expense(
                session_id=session.pk,
                actor=request.user,
                **form.cleaned_data,
            )
        except ValidationError as error:
            _add_validation_error(form, error)
        else:
            messages.success(request, "Egreso registrado.")
            return redirect("finance:index")
    return _render_open_session_with_form(
        request,
        session,
        expense_form=form,
    )


def _render_open_session_with_form(
    request,
    session,
    *,
    payment_form=None,
    expense_form=None,
    close_form=None,
):
    can_operate = (
        session.opened_by_id == request.user.pk
        or request.user.has_perm("finance.cash.override")
    )
    return render(
        request,
        "finance/index.html",
        {
            "session": session,
            "can_operate": can_operate,
            "open_form": None,
            "payment_form": payment_form or (PaymentForm() if can_operate else None),
            "expense_form": expense_form or (ExpenseForm() if can_operate else None),
            "close_form": close_form or (CloseCashForm() if can_operate else None),
            "expected_cash": (
                cash_expected_for_session(session) if can_operate else None
            ),
            "sessions": _sessions_list(),
        },
    )


@login_required
def cash_close(request):
    _require_permission(request.user, "finance.cash.manage")
    if request.method != "POST":
        raise PermissionDenied
    session = get_open_session()
    if not session:
        messages.error(request, "No hay una caja abierta para cerrar.")
        return redirect("finance:index")
    form = CloseCashForm(request.POST)
    if form.is_valid():
        try:
            closed = close_cash_session(
                session_id=session.pk,
                actor=request.user,
                **form.cleaned_data,
            )
        except ValidationError as error:
            _add_validation_error(form, error)
        else:
            messages.success(
                request,
                f"Caja cerrada. Diferencia: S/ {closed.difference_cash:.2f}.",
            )
            return redirect("finance:index")
    return _render_open_session_with_form(request, session, close_form=form)


@login_required
def reports(request):
    _require_permission(request.user, "reports.financial.view")
    today = timezone.localdate()
    initial = {"start_date": today, "end_date": today}
    form = ReportFilterForm(request.GET or initial)
    if not form.is_valid():
        return render(
            request,
            "finance/reports.html",
            {"form": form, "report": None},
        )
    start_date = form.cleaned_data["start_date"]
    end_date = form.cleaned_data["end_date"]
    payments = Payment.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
    ).select_related("work_order", "created_by", "session")
    expenses = Expense.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
    ).select_related("created_by", "session")
    sessions = CashSession.objects.filter(
        closed_at__date__gte=start_date,
        closed_at__date__lte=end_date,
    ).select_related("opened_by", "closed_by")
    payment_totals = {
        method: payments.filter(method=method).aggregate(total=Sum("amount"))[
            "total"
        ]
        or Decimal("0.00")
        for method, _label in Payment.Method.choices
    }
    expense_totals = {
        method: expenses.filter(method=method).aggregate(total=Sum("amount"))[
            "total"
        ]
        or Decimal("0.00")
        for method, _label in Payment.Method.choices
    }
    payment_total = sum(payment_totals.values(), Decimal("0.00"))
    expense_total = sum(expense_totals.values(), Decimal("0.00"))
    method_summary = [
        {
            "label": label,
            "payments": payment_totals[method],
            "expenses": expense_totals[method],
        }
        for method, label in Payment.Method.choices
    ]
    return render(
        request,
        "finance/reports.html",
        {
            "form": form,
            "report": {
                "start_date": start_date,
                "end_date": end_date,
                "payments": payments,
                "expenses": expenses,
                "sessions": sessions,
                "payment_totals": payment_totals,
                "expense_totals": expense_totals,
                "payment_methods": Payment.Method.choices,
                "method_summary": method_summary,
                "payment_total": payment_total,
                "expense_total": expense_total,
                "net_total": payment_total - expense_total,
            },
        },
    )
