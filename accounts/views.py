from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from accounts.permissions import ROLE_PERMISSIONS


@login_required
def profile(request):
    capabilities = sorted(ROLE_PERMISSIONS.get(request.user.role, set()))
    return render(
        request,
        "accounts/profile.html",
        {"user": request.user, "capabilities": capabilities},
    )
