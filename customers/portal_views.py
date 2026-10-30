from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from customers.models import Customer
from customers.portal_services import (
    consume_customer_portal_code,
    respond_to_portal_order,
)
from workorders.models import WorkOrder


PORTAL_SESSION_KEY = "customer_portal_customer_id"
PORTAL_SESSION_SECONDS = 12 * 60 * 60


@never_cache
def portal_login(request):
    error = None
    if request.method == "POST":
        code = request.POST.get("code", "").strip()
        customer_id = consume_customer_portal_code(code)
        if customer_id is None:
            error = "El código no es válido o venció. Solicita uno nuevo al taller."
        else:
            request.session.flush()
            request.session[PORTAL_SESSION_KEY] = customer_id
            request.session.set_expiry(PORTAL_SESSION_SECONDS)
            return redirect("customer_portal:home")
    return render(request, "customers/portal_login.html", {"error": error})


@never_cache
def portal_home(request):
    customer_id = request.session.get(PORTAL_SESSION_KEY)
    if customer_id is None:
        return redirect("customer_portal:login")
    customer = get_object_or_404(Customer, pk=customer_id)
    orders = (
        WorkOrder.objects.filter(
            customer_id=customer.pk,
            motorcycle__customer_id=customer.pk,
        )
        .exclude(status=WorkOrder.Status.DRAFT)
        .select_related("motorcycle")
        .prefetch_related("lines")
        .order_by("-created_at", "-pk")[:50]
    )
    return render(
        request,
        "customers/portal_home.html",
        {"customer": customer, "work_orders": orders},
    )


@require_POST
@never_cache
def portal_order_response(request, pk):
    customer_id = request.session.get(PORTAL_SESSION_KEY)
    if customer_id is None:
        return redirect("customer_portal:login")
    get_object_or_404(
        WorkOrder,
        pk=pk,
        customer_id=customer_id,
        status=WorkOrder.Status.WAITING_APPROVAL,
    )
    decision = request.POST.get("decision", "")
    try:
        respond_to_portal_order(
            work_order_id=pk,
            customer_id=customer_id,
            decision=decision,
        )
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
    else:
        messages.success(
            request,
            "Tu respuesta quedó registrada. El taller recibió la actualización.",
        )
    return redirect("customer_portal:home")


@require_POST
@never_cache
def portal_logout(request):
    request.session.pop(PORTAL_SESSION_KEY, None)
    request.session.cycle_key()
    return redirect("customer_portal:login")
