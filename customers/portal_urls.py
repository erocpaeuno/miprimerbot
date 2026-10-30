from django.urls import path

from customers import portal_views

app_name = "customer_portal"

urlpatterns = [
    path("", portal_views.portal_home, name="home"),
    path("ingresar/", portal_views.portal_login, name="login"),
    path("salir/", portal_views.portal_logout, name="logout"),
    path(
        "ordenes/<int:pk>/respuesta/",
        portal_views.portal_order_response,
        name="order_response",
    ),
]
