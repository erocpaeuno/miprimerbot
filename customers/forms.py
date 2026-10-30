import re

from django import forms

from customers.models import Customer, Motorcycle


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["full_name", "dni", "phone", "email", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_dni(self):
        dni = self.cleaned_data.get("dni")
        if not dni:
            return None
        dni = dni.strip()
        if not re.fullmatch(r"\d{8}", dni):
            raise forms.ValidationError("El DNI debe contener exactamente 8 dígitos.")
        return dni


class MotorcycleForm(forms.ModelForm):
    class Meta:
        model = Motorcycle
        fields = [
            "customer",
            "plate",
            "make",
            "model",
            "year",
            "motorcycle_type",
            "current_mileage",
        ]

    def clean_plate(self):
        plate = re.sub(r"\s+", " ", self.cleaned_data["plate"].strip()).upper()
        normalized = re.sub(r"[^A-Z0-9]", "", plate)
        if not normalized:
            raise forms.ValidationError("Ingresa una placa o código válido.")
        duplicates = Motorcycle.objects.filter(plate_normalized=normalized)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError(
                "Ya existe una motocicleta con esa placa o código."
            )
        return plate

    def clean_current_mileage(self):
        mileage = self.cleaned_data["current_mileage"]
        if mileage < 0:
            raise forms.ValidationError("El kilometraje no puede ser negativo.")
        return mileage
