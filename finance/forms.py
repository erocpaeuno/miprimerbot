from decimal import Decimal

from django import forms
from django.db.models import Sum

from finance.models import CashSession, Expense, Payment
from workorders.models import WorkOrder


class OpenCashForm(forms.Form):
    opening_cash = forms.DecimalField(
        label="Fondo inicial (S/)",
        min_value=Decimal("0.00"),
        max_digits=10,
        decimal_places=2,
    )


class PaymentForm(forms.Form):
    work_order = forms.ModelChoiceField(
        label="Orden",
        queryset=WorkOrder.objects.none(),
    )
    amount = forms.DecimalField(
        label="Importe (S/)",
        min_value=Decimal("0.01"),
        max_digits=10,
        decimal_places=2,
    )
    method = forms.ChoiceField(
        label="Medio de pago",
        choices=Payment.Method.choices,
    )
    note = forms.CharField(label="Referencia", max_length=180, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["work_order"].queryset = WorkOrder.objects.filter(
            status__in=[WorkOrder.Status.READY, WorkOrder.Status.DELIVERED]
        ).select_related("customer").order_by("-created_at")

    def clean(self):
        cleaned_data = super().clean()
        work_order = cleaned_data.get("work_order")
        if work_order:
            paid = work_order.payments.aggregate(total=Sum("amount"))["total"] or Decimal(
                "0.00"
            )
            balance = work_order.total - paid
            if balance <= 0:
                self.add_error("work_order", "La orden ya está pagada.")
            elif cleaned_data.get("amount") and cleaned_data["amount"] > balance:
                self.add_error(
                    "amount",
                    f"El importe supera el saldo pendiente de S/ {balance:.2f}.",
                )
        return cleaned_data


class ExpenseForm(forms.Form):
    category = forms.ChoiceField(
        label="Categoría",
        choices=Expense.Category.choices,
    )
    description = forms.CharField(label="Descripción", max_length=180)
    amount = forms.DecimalField(
        label="Importe (S/)",
        min_value=Decimal("0.01"),
        max_digits=10,
        decimal_places=2,
    )
    method = forms.ChoiceField(
        label="Medio de pago",
        choices=Payment.Method.choices,
    )
    reference = forms.CharField(
        label="Referencia",
        max_length=180,
        required=False,
    )


class CloseCashForm(forms.Form):
    counted_cash = forms.DecimalField(
        label="Efectivo contado (S/)",
        min_value=Decimal("0.00"),
        max_digits=10,
        decimal_places=2,
    )


class ReportFilterForm(forms.Form):
    start_date = forms.DateField(
        label="Desde",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    end_date = forms.DateField(
        label="Hasta",
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "La fecha final debe ser igual o posterior.")
        return cleaned_data
