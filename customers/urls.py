from django.urls import path

from customers import views

app_name = "customers"

urlpatterns = [
    path("", views.customer_list, name="customer_list"),
    path("nuevo/", views.customer_create, name="customer_create"),
    path("<int:pk>/", views.customer_detail, name="customer_detail"),
    path(
        "<int:pk>/telegram/vincular/",
        views.customer_telegram_link,
        name="customer_telegram_link",
    ),
    path(
        "<int:pk>/portal/codigo/",
        views.customer_portal_code,
        name="customer_portal_code",
    ),
    path("<int:pk>/editar/", views.customer_update, name="customer_update"),
    path("motocicletas/", views.motorcycle_list, name="motorcycle_list"),
    path(
        "motocicletas/nueva/",
        views.motorcycle_create,
        name="motorcycle_create",
    ),
    path(
        "motocicletas/<int:pk>/",
        views.motorcycle_detail,
        name="motorcycle_detail",
    ),
    path(
        "motocicletas/<int:pk>/editar/",
        views.motorcycle_update,
        name="motorcycle_update",
    ),
]
