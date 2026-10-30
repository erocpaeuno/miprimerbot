from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("cuentas/", include("accounts.urls")),
    path("clientes/", include("customers.urls")),
    path("portal-cliente/", include("customers.portal_urls")),
    path("catalogo/", include("inventory.catalog_urls")),
    path("inventario/", include("inventory.urls")),
    path("ordenes/", include("workorders.urls")),
    path("mantenimiento/", include("maintenance.urls")),
    path("caja/", include("finance.urls")),
    path("telegram/", include("messaging.urls")),
    path("", include("core.urls")),
]
