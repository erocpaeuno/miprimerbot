from django.contrib.auth import views as auth_views
from django.urls import path

from accounts.views import profile

app_name = "accounts"

urlpatterns = [
    path(
        "entrar/",
        auth_views.LoginView.as_view(template_name="accounts/login.html"),
        name="login",
    ),
    path("salir/", auth_views.LogoutView.as_view(), name="logout"),
    path("perfil/", profile, name="profile"),
]
