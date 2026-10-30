from django.urls import path

from inventory import views

app_name = "inventory"

urlpatterns = [
    path("repuestos/", views.part_list, name="part_list"),
    path("repuestos/nuevo/", views.part_create, name="part_create"),
    path(
        "repuestos/<int:pk>/",
        views.part_detail,
        name="part_detail",
    ),
    path(
        "repuestos/<int:pk>/editar/",
        views.part_update,
        name="part_update",
    ),
    path(
        "repuestos/<int:part_pk>/movimientos/nuevo/",
        views.movement_create,
        name="movement_create",
    ),
    path("movimientos/", views.movement_list, name="movement_list"),
]
