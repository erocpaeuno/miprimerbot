from django.urls import path

from maintenance import views

app_name = "maintenance"

urlpatterns = [
    path("", views.index, name="index"),
    path("planes/nuevo/", views.plan_create, name="plan_create"),
    path("planes/<int:pk>/", views.plan_detail, name="plan_detail"),
    path("planes/<int:pk>/editar/", views.plan_update, name="plan_update"),
    path(
        "planes/<int:pk>/recordatorios/nuevo/",
        views.reminder_create,
        name="reminder_create",
    ),
    path(
        "recordatorios/<int:pk>/registrar-envio/",
        views.reminder_mark_sent,
        name="reminder_mark_sent",
    ),
    path(
        "recordatorios/<int:pk>/estado/",
        views.reminder_update_status,
        name="reminder_update_status",
    ),
]
