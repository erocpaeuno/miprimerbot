from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from inventory.forms import InventoryMovementForm, PartForm, ServiceForm
from inventory.models import InventoryMovement, Part, Service
from inventory.services import record_movement


@login_required
@permission_required("catalog.view_services", raise_exception=True)
def service_list(request):
    services = Service.objects.all()
    query = request.GET.get("q", "").strip()
    if query:
        services = services.filter(
            Q(name__icontains=query) | Q(description__icontains=query)
        )
    return render(
        request,
        "inventory/service_list.html",
        {"services": services, "query": query},
    )


@login_required
@permission_required("catalog.manage_services", raise_exception=True)
def service_create(request):
    form = ServiceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("catalog:service_list")
    return render(
        request,
        "inventory/service_form.html",
        {"form": form, "title": "Registrar servicio"},
    )


@login_required
@permission_required("catalog.manage_services", raise_exception=True)
def service_update(request, pk):
    service = get_object_or_404(Service, pk=pk)
    form = ServiceForm(request.POST or None, instance=service)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("catalog:service_list")
    return render(
        request,
        "inventory/service_form.html",
        {"form": form, "title": "Editar servicio"},
    )


@login_required
@permission_required("inventory.view", raise_exception=True)
def part_list(request):
    parts = Part.objects.all()
    query = request.GET.get("q", "").strip()
    if query:
        parts = parts.filter(
            Q(sku__icontains=query)
            | Q(name__icontains=query)
            | Q(description__icontains=query)
        )
    return render(
        request,
        "inventory/part_list.html",
        {"parts": parts, "query": query},
    )


@login_required
@permission_required("inventory.manage", raise_exception=True)
def part_create(request):
    form = PartForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        part = form.save()
        return redirect(part)
    return render(
        request,
        "inventory/part_form.html",
        {"form": form, "title": "Registrar repuesto"},
    )


@login_required
@permission_required("inventory.view", raise_exception=True)
def part_detail(request, pk):
    part = get_object_or_404(Part, pk=pk)
    movements = part.movements.select_related("created_by")[:50]
    return render(
        request,
        "inventory/part_detail.html",
        {"part": part, "movements": movements},
    )


@login_required
@permission_required("inventory.manage", raise_exception=True)
def part_update(request, pk):
    part = get_object_or_404(Part, pk=pk)
    form = PartForm(request.POST or None, instance=part)
    if request.method == "POST" and form.is_valid():
        part = form.save()
        return redirect(part)
    return render(
        request,
        "inventory/part_form.html",
        {"form": form, "title": "Editar repuesto", "part": part},
    )


@login_required
@permission_required("inventory.manage", raise_exception=True)
def movement_create(request, part_pk):
    part = get_object_or_404(Part, pk=part_pk)
    form = InventoryMovementForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            record_movement(
                part_id=part.pk,
                actor=request.user,
                **form.cleaned_data,
            )
        except ValidationError as error:
            for field, errors in error.message_dict.items():
                for message in errors:
                    form.add_error(field if field in form.fields else None, message)
        else:
            return redirect(part)
    return render(
        request,
        "inventory/movement_form.html",
        {"form": form, "part": part},
    )


@login_required
@permission_required("inventory.manage", raise_exception=True)
def movement_list(request):
    movements = InventoryMovement.objects.select_related("part", "created_by")
    return render(
        request,
        "inventory/movement_list.html",
        {"movements": movements[:100]},
    )
