from decimal import Decimal

from django import forms

from inventory.models import InventoryMovement, Part, Service


class ServiceForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = [
            "name",
            "description",
            "default_price",
            "estimated_minutes",
            "active",
        ]
        widgets = {
            "default_price": forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
            "estimated_minutes": forms.NumberInput(attrs={"min": "1", "step": "1"}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_default_price(self):
        price = self.cleaned_data["default_price"]
        if price < Decimal("0"):
            raise forms.ValidationError("El precio no puede ser negativo.")
        return price


class PartForm(forms.ModelForm):
    class Meta:
        model = Part
        fields = [
            "sku",
            "name",
            "description",
            "unit",
            "unit_price",
            "reorder_level",
            "active",
        ]
        widgets = {
            "unit_price": forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
            "reorder_level": forms.NumberInput(
                attrs={"min": "0", "step": "0.001"}
            ),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_sku(self):
        return self.cleaned_data["sku"].strip().upper()


class InventoryMovementForm(forms.Form):
    movement_type = forms.ChoiceField(
        label="Tipo",
        choices=InventoryMovement.MovementType.choices,
    )
    quantity = forms.DecimalField(
        label="Cantidad o existencia contada",
        min_value=Decimal("0"),
        max_digits=12,
        decimal_places=3,
        widget=forms.NumberInput(attrs={"min": "0", "step": "0.001"}),
    )
    unit_cost = forms.DecimalField(
        label="Costo unitario (opcional)",
        required=False,
        min_value=Decimal("0"),
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
    )
    note = forms.CharField(label="Motivo o referencia", max_length=240)

    def clean(self):
        cleaned_data = super().clean()
        movement_type = cleaned_data.get("movement_type")
        quantity = cleaned_data.get("quantity")
        if (
            movement_type
            and movement_type != InventoryMovement.MovementType.ADJUSTMENT
            and quantity is not None
            and quantity <= 0
        ):
            self.add_error("quantity", "El ingreso o la salida debe ser mayor que cero.")
        return cleaned_data
