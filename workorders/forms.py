from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from accounts.models import StaffUser
from customers.models import Customer, Motorcycle
from inventory.models import Part, Service
from workorders.models import CustomerApproval, WorkOrder, WorkOrderLine
from workorders.services import (
    ALLOWED_TRANSITIONS,
    TECHNICIAN_TRANSITIONS,
    add_work_order_line,
)


class WorkOrderForm(forms.ModelForm):
    class Meta:
        model = WorkOrder
        fields = [
            "customer",
            "motorcycle",
            "assigned_to",
            "mileage",
            "complaint",
            "diagnosis",
            "notes",
        ]
        widgets = {
            "complaint": forms.Textarea(attrs={"rows": 3}),
            "diagnosis": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.order_by("full_name")
        self.fields["motorcycle"].queryset = Motorcycle.objects.select_related(
            "customer"
        ).order_by("plate")
        self.fields["assigned_to"].queryset = StaffUser.objects.filter(
            role=StaffUser.Role.TECHNICIAN,
            is_active=True,
        ).order_by("first_name", "username")
        self.fields["assigned_to"].required = False

    def clean(self):
        cleaned_data = super().clean()
        customer = cleaned_data.get("customer")
        motorcycle = cleaned_data.get("motorcycle")
        if customer and motorcycle and motorcycle.customer_id != customer.pk:
            self.add_error(
                "motorcycle",
                "La motocicleta no pertenece al cliente seleccionado.",
            )
        mileage = cleaned_data.get("mileage")
        if motorcycle and mileage is not None and mileage < motorcycle.current_mileage:
            self.add_error(
                "mileage",
                "El kilometraje no puede ser menor al último registrado.",
            )
        return cleaned_data


class WorkOrderLineForm(forms.Form):
    line_type = forms.ChoiceField(
        label="Tipo",
        choices=WorkOrderLine.LineType.choices,
    )
    service = forms.ModelChoiceField(
        label="Servicio",
        queryset=Service.objects.none(),
        required=False,
    )
    part = forms.ModelChoiceField(
        label="Repuesto",
        queryset=Part.objects.none(),
        required=False,
    )
    quantity = forms.DecimalField(
        label="Cantidad",
        min_value=Decimal("0.001"),
        max_digits=10,
        decimal_places=3,
        widget=forms.NumberInput(attrs={"min": "0.001", "step": "0.001"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["service"].queryset = Service.objects.filter(
            active=True
        ).order_by("name")
        self.fields["part"].queryset = Part.objects.filter(active=True).order_by(
            "name"
        )

    def clean(self):
        cleaned_data = super().clean()
        line_type = cleaned_data.get("line_type")
        service = cleaned_data.get("service")
        part = cleaned_data.get("part")
        if line_type == WorkOrderLine.LineType.SERVICE:
            if not service:
                self.add_error("service", "Selecciona un servicio.")
            if part:
                self.add_error("part", "Una línea de servicio no lleva repuesto.")
        elif line_type == WorkOrderLine.LineType.PART:
            if not part:
                self.add_error("part", "Selecciona un repuesto.")
            if service:
                self.add_error("service", "Una línea de repuesto no lleva servicio.")
        return cleaned_data

    def save(self, *, work_order, actor):
        item = (
            self.cleaned_data["service"]
            if self.cleaned_data["line_type"] == WorkOrderLine.LineType.SERVICE
            else self.cleaned_data["part"]
        )
        return add_work_order_line(
            work_order_id=work_order.pk,
            line_type=self.cleaned_data["line_type"],
            item_id=item.pk,
            quantity=self.cleaned_data["quantity"],
            actor=actor,
        )


class ApprovalForm(forms.Form):
    channel = forms.ChoiceField(
        label="Medio",
        choices=CustomerApproval.Channel.choices,
    )
    evidence_note = forms.CharField(
        label="Detalle de la confirmación recibida",
        max_length=300,
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class TechnicianUpdateForm(forms.Form):
    diagnosis = forms.CharField(
        label="Diagnóstico",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    notes = forms.CharField(
        label="Notas de trabajo",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class TransitionForm(forms.Form):
    status = forms.ChoiceField(label="Siguiente estado")

    def __init__(self, *args, work_order, actor, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [
            (status, WorkOrder.Status(status).label)
            for status in ALLOWED_TRANSITIONS[work_order.status]
            if status != WorkOrder.Status.APPROVED
        ]
        if actor.role == StaffUser.Role.TECHNICIAN and not actor.is_superuser:
            choices = [
                choice
                for choice in choices
                if (work_order.status, choice[0]) in TECHNICIAN_TRANSITIONS
            ]
        self.fields["status"].choices = choices

    def clean_status(self):
        status = self.cleaned_data["status"]
        if status not in WorkOrder.Status.values:
            raise ValidationError("Estado inválido.")
        return status
