from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from customers.forms import CustomerForm, MotorcycleForm
from customers.models import Customer, Motorcycle
from customers.portal_services import issue_customer_portal_code
from messaging.models import TelegramAccount
from messaging.services import issue_link_token


@login_required
@permission_required("customers.manage_customers", raise_exception=True)
def customer_list(request):
    query = request.GET.get("q", "").strip()
    customers = Customer.objects.all()
    if query:
        customers = customers.filter(
            Q(full_name__icontains=query)
            | Q(phone__icontains=query)
            | Q(dni__icontains=query)
        )
    return render(
        request,
        "customers/customer_list.html",
        {"customers": customers, "query": query},
    )


@login_required
@permission_required("customers.manage_customers", raise_exception=True)
def customer_create(request):
    form = CustomerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        customer = form.save()
        return redirect(customer)
    return render(
        request,
        "customers/customer_form.html",
        {"form": form, "title": "Registrar cliente"},
    )


@login_required
@permission_required("customers.manage_customers", raise_exception=True)
def customer_detail(request, pk):
    customer = get_object_or_404(
        Customer.objects.prefetch_related("motorcycles"),
        pk=pk,
    )
    return render(
        request,
        "customers/customer_detail.html",
        {
            "customer": customer,
            "telegram_account": TelegramAccount.objects.filter(
                customer=customer
            ).first(),
            "telegram_bot_username": settings.TELEGRAM_BOT_USERNAME,
            "portal_code": None,
        },
    )


@login_required
@permission_required("customers.manage_customers", raise_exception=True)
@require_POST
def customer_telegram_link(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    try:
        token = issue_link_token(customer_id=customer.pk, actor=request.user)
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
        return redirect(customer)
    return render(
        request,
        "customers/customer_detail.html",
        {
            "customer": customer,
            "telegram_account": TelegramAccount.objects.filter(
                customer=customer
            ).first(),
            "telegram_bot_username": settings.TELEGRAM_BOT_USERNAME,
            "telegram_link_token": token,
            "portal_code": None,
        },
    )


@login_required
@permission_required("customers.manage_customers", raise_exception=True)
@require_POST
@never_cache
def customer_portal_code(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    try:
        token = issue_customer_portal_code(
            customer_id=customer.pk,
            actor=request.user,
        )
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
        return redirect(customer)
    return render(
        request,
        "customers/customer_detail.html",
        {
            "customer": customer,
            "telegram_account": TelegramAccount.objects.filter(
                customer=customer
            ).first(),
            "telegram_bot_username": settings.TELEGRAM_BOT_USERNAME,
            "portal_code": token,
            "telegram_link_token": None,
        },
    )


@login_required
@permission_required("customers.manage_customers", raise_exception=True)
def customer_update(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    form = CustomerForm(request.POST or None, instance=customer)
    if request.method == "POST" and form.is_valid():
        customer = form.save()
        return redirect(customer)
    return render(
        request,
        "customers/customer_form.html",
        {"form": form, "title": "Editar cliente"},
    )


@login_required
@permission_required("vehicles.manage_vehicles", raise_exception=True)
def motorcycle_list(request):
    query = request.GET.get("q", "").strip()
    motorcycles = Motorcycle.objects.select_related("customer")
    if query:
        motorcycles = motorcycles.filter(
            Q(plate__icontains=query)
            | Q(make__icontains=query)
            | Q(model__icontains=query)
            | Q(customer__full_name__icontains=query)
        )
    return render(
        request,
        "customers/motorcycle_list.html",
        {"motorcycles": motorcycles, "query": query},
    )


@login_required
@permission_required("vehicles.manage_vehicles", raise_exception=True)
def motorcycle_create(request):
    initial = {}
    customer_id = request.GET.get("customer", "")
    if customer_id.isdecimal():
        customer = Customer.objects.filter(pk=customer_id).first()
        if customer:
            initial["customer"] = customer
    form = MotorcycleForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        motorcycle = form.save()
        return redirect(motorcycle)
    return render(
        request,
        "customers/motorcycle_form.html",
        {"form": form, "title": "Registrar motocicleta"},
    )


@login_required
@permission_required("vehicles.manage_vehicles", raise_exception=True)
def motorcycle_detail(request, pk):
    motorcycle = get_object_or_404(
        Motorcycle.objects.select_related("customer"),
        pk=pk,
    )
    return render(
        request,
        "customers/motorcycle_detail.html",
        {"motorcycle": motorcycle},
    )


@login_required
@permission_required("vehicles.manage_vehicles", raise_exception=True)
def motorcycle_update(request, pk):
    motorcycle = get_object_or_404(Motorcycle, pk=pk)
    form = MotorcycleForm(request.POST or None, instance=motorcycle)
    if request.method == "POST" and form.is_valid():
        motorcycle = form.save()
        return redirect(motorcycle)
    return render(
        request,
        "customers/motorcycle_form.html",
        {"form": form, "title": "Editar motocicleta"},
    )
