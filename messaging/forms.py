from django import forms


class OfferCampaignForm(forms.Form):
    message = forms.CharField(
        label="Contenido de la oferta",
        max_length=900,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Se enviará solo a clientes que aceptaron recibir ofertas.",
    )
