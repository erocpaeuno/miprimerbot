from django import forms
from django.core.exceptions import ValidationError

from customers.models import Motorcycle
from maintenance.models import MaintenancePlan, ReminderLog


class MaintenancePlanForm(forms.ModelForm):
    class Meta:
        model = MaintenancePlan
        fields = [
            "motorcycle",
            "service_name",
            "last_completed_at",
            "last_completed_mileage",
            "due_date",
            "due_mileage",
            "status",
            "notes",
        ]
        widgets = {
            "last_completed_at": forms.DateInput(attrs={"type": "date"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["motorcycle"].queryset = Motorcycle.objects.select_related(
            "customer"
        ).order_by("plate")

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get("due_date") and cleaned_data.get("due_mileage") is None:
            raise ValidationError(
                "Indica una fecha o un kilometraje para el próximo mantenimiento."
            )
        motorcycle = cleaned_data.get("motorcycle")
        status = cleaned_data.get("status")
        due_mileage = cleaned_data.get("due_mileage")
        last_mileage = cleaned_data.get("last_completed_mileage")
        if due_mileage is not None and last_mileage is not None and due_mileage <= last_mileage:
            self.add_error(
                "due_mileage",
                "El kilometraje previsto debe superar al del último servicio.",
            )
        if (
            status == MaintenancePlan.Status.ACTIVE
            and motorcycle
            and due_mileage is not None
            and due_mileage <= motorcycle.current_mileage
        ):
            self.add_error(
                "due_mileage",
                "El kilometraje previsto debe superar el kilometraje actual.",
            )
        return cleaned_data

    def save(self, *, actor, commit=True):
        plan = super().save(commit=False)
        if not plan.pk:
            plan.created_by = actor
        if commit:
            plan.save()
        return plan


class ReminderForm(forms.ModelForm):
    class Meta:
        model = ReminderLog
        fields = ["channel", "scheduled_for", "note"]
        widgets = {
            "scheduled_for": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, plan, **kwargs):
        super().__init__(*args, **kwargs)
        self.plan = plan

    def clean(self):
        cleaned_data = super().clean()
        channel = cleaned_data.get("channel")
        scheduled_for = cleaned_data.get("scheduled_for")
        if channel and scheduled_for and ReminderLog.objects.filter(
            plan=self.plan,
            channel=channel,
            scheduled_for=scheduled_for,
        ).exists():
            self.add_error(
                "scheduled_for",
                "Ya existe un recordatorio de ese canal y fecha para este plan.",
            )
        return cleaned_data


class ReminderStatusForm(forms.Form):
    status = forms.ChoiceField(
        choices=[
            (ReminderLog.Status.FAILED, ReminderLog.Status.FAILED.label),
            (ReminderLog.Status.CANCELLED, ReminderLog.Status.CANCELLED.label),
        ]
    )
    note = forms.CharField(max_length=300, required=False)


class MarkReminderSentForm(forms.Form):
    note = forms.CharField(
        label="Constancia del envío",
        max_length=300,
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    def clean_note(self):
        note = self.cleaned_data["note"].strip()
        if not note:
            raise ValidationError(
                "Describe brevemente el envío que se realizó."
            )
        return note
