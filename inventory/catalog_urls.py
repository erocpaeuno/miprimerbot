from django.urls import path

from inventory import views

app_name = "catalog"

urlpatterns = [
    path("servicios/", views.service_list, name="service_list"),
    path("servicios/nuevo/", views.service_create, name="service_create"),
    path(
        "servicios/<int:pk>/editar/",
        views.service_update,
        name="service_update",
    ),
]
