from django.urls import path

from messaging import views

app_name = "messaging"

urlpatterns = [
    path("webhook/", views.webhook, name="webhook"),
    path("ofertas/", views.offers, name="offers"),
]
