from django.urls import path

from finance import views

app_name = "finance"

urlpatterns = [
    path("", views.index, name="index"),
    path("abrir/", views.cash_open, name="open"),
    path("pagos/registrar/", views.payment_create, name="payment_create"),
    path("egresos/registrar/", views.expense_create, name="expense_create"),
    path("cerrar/", views.cash_close, name="close"),
    path("reportes/", views.reports, name="reports"),
]
