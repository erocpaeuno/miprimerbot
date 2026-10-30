from django.urls import path

from core.views import health


urlpatterns = [
    path("", health, name="health"),
]
