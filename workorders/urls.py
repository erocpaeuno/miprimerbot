from django.urls import path

from workorders import views

app_name = "workorders"

urlpatterns = [
    path("", views.order_list, name="list"),
    path("nueva/", views.order_create, name="create"),
    path("<int:pk>/", views.order_detail, name="detail"),
    path("<int:pk>/editar/", views.order_update, name="update"),
    path("<int:pk>/lineas/", views.order_add_line, name="add_line"),
    path(
        "<int:pk>/lineas/<int:line_pk>/retirar/",
        views.order_remove_line,
        name="remove_line",
    ),
    path(
        "<int:pk>/diagnostico/",
        views.order_update_assigned,
        name="update_assigned",
    ),
    path("<int:pk>/estado/", views.order_transition, name="transition"),
    path("<int:pk>/aprobar/", views.order_approve, name="approve"),
]
