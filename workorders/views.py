from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from workorders.forms import (
    ApprovalForm,
    TechnicianUpdateForm,
    TransitionForm,
    WorkOrderForm,
    WorkOrderLineForm,
)
from workorders.models import WorkOrder, WorkOrderLine
from workorders.services import (
    add_work_order_line,
    approve_work_order,
    create_work_order,
    transition_work_order,
    remove_work_order_line,
    update_work_order,
    update_assigned_work,
)


def _can_view_order(user, work_order):
    return user.has_perm("workorders.view_all") or (
        user.has_perm("workorders.view_assigned")
        and work_order.assigned_to_id == user.pk
    )


def _can_add_line(user, work_order):
    if user.has_perm("workorders.manage"):
        return work_order.can_change_lines
    return (
        user.has_perm("workorders.update_assigned")
        and work_order.assigned_to_id == user.pk
        and work_order.status
        in {WorkOrder.Status.DIAGNOSING, WorkOrder.Status.IN_PROGRESS}
    )


@login_required
def order_list(request):
    if not (
        request.user.has_perm("workorders.view_all")
        or request.user.has_perm("workorders.view_assigned")
    ):
        raise PermissionDenied
    orders = WorkOrder.objects.select_related(
        "customer",
        "motorcycle",
        "assigned_to",
    ).prefetch_related("lines")
    if not request.user.has_perm("workorders.view_all"):
        orders = orders.filter(assigned_to=request.user)

    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    if query:
        orders = orders.filter(
            Q(order_number__icontains=query)
            | Q(customer__full_name__icontains=query)
            | Q(motorcycle__plate__icontains=query)
        )
    if status in WorkOrder.Status.values:
        orders = orders.filter(status=status)
    return render(
        request,
        "workorders/order_list.html",
        {
            "orders": orders,
            "query": query,
            "selected_status": status,
            "statuses": WorkOrder.Status.choices,
            "can_manage": request.user.has_perm("workorders.manage"),
        },
    )


@login_required
def order_create(request):
    if not request.user.has_perm("workorders.manage"):
        raise PermissionDenied
    form = WorkOrderForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        work_order = create_work_order(
            data=form.cleaned_data,
            actor=request.user,
        )
        return redirect(work_order)
    return render(
        request,
        "workorders/order_form.html",
        {"form": form, "title": "Crear orden de trabajo"},
    )


@login_required
def order_detail(request, pk):
    work_order = get_object_or_404(
        WorkOrder.objects.select_related(
            "customer",
            "motorcycle",
            "assigned_to",
            "created_by",
        ).prefetch_related(
            "lines__service",
            "lines__part",
            "events__actor",
        ),
        pk=pk,
    )
    if not _can_view_order(request.user, work_order):
        raise Http404

    can_manage = request.user.has_perm("workorders.manage")
    can_update_assigned = (
        request.user.has_perm("workorders.update_assigned")
        and work_order.assigned_to_id == request.user.pk
    )
    can_change_details = can_manage and work_order.status in {
        WorkOrder.Status.DRAFT,
        WorkOrder.Status.RECEIVED,
        WorkOrder.Status.DIAGNOSING,
    }
    can_add_line = _can_add_line(request.user, work_order)
    can_update_work = (
        can_update_assigned
        and work_order.status
        in {WorkOrder.Status.DIAGNOSING, WorkOrder.Status.IN_PROGRESS}
    )
    can_see_prices = can_manage or request.user.has_perm(
        "finance.payments.manage"
    )
    line_form = WorkOrderLineForm() if can_add_line else None
    transition_form = None
    if can_manage or can_update_assigned:
        transition_form = TransitionForm(
            work_order=work_order,
            actor=request.user,
        )
    return render(
        request,
        "workorders/order_detail.html",
        {
            "work_order": work_order,
            "can_manage": can_manage,
            "can_update_assigned": can_update_assigned,
            "can_change_details": can_change_details,
            "can_add_line": can_add_line,
            "can_update_work": can_update_work,
            "technician_form": (
                TechnicianUpdateForm(
                    initial={
                        "diagnosis": work_order.diagnosis,
                        "notes": work_order.notes,
                    }
                )
                if can_update_work
                else None
            ),
            "can_see_prices": can_see_prices,
            "line_form": line_form,
            "transition_form": transition_form,
            "can_approve": request.user.has_perm("workorders.approve")
            and work_order.status == WorkOrder.Status.WAITING_APPROVAL,
            "can_see_approval": request.user.has_perm("workorders.approve"),
        },
    )


@login_required
def order_update(request, pk):
    work_order = get_object_or_404(WorkOrder, pk=pk)
    if not request.user.has_perm("workorders.manage"):
        raise PermissionDenied
    form = WorkOrderForm(request.POST or None, instance=work_order)
    if request.method == "POST" and form.is_valid():
        try:
            update_work_order(
                work_order_id=work_order.pk,
                data=form.cleaned_data,
                actor=request.user,
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            return redirect(work_order)
    return render(
        request,
        "workorders/order_form.html",
        {"form": form, "title": f"Editar {work_order.order_number}"},
    )


@login_required
def order_add_line(request, pk):
    work_order = get_object_or_404(WorkOrder, pk=pk)
    if request.method != "POST":
        raise PermissionDenied
    if not _can_add_line(request.user, work_order):
        raise PermissionDenied
    form = WorkOrderLineForm(request.POST)
    if form.is_valid():
        try:
            form.save(work_order=work_order, actor=request.user)
        except ValidationError as error:
            if hasattr(error, "message_dict"):
                for field, errors in error.message_dict.items():
                    for message in errors:
                        form.add_error(
                            field if field in form.fields else None,
                            message,
                        )
            else:
                form.add_error(None, error)
        else:
            messages.success(request, "Línea añadida a la orden.")
            return redirect(work_order)
    return render(
        request,
        "workorders/order_detail.html",
        _detail_context(request, work_order, line_form=form),
    )


@login_required
def order_remove_line(request, pk, line_pk):
    if request.method != "POST":
        raise PermissionDenied
    work_order = get_object_or_404(WorkOrder, pk=pk)
    if not (
        request.user.has_perm("workorders.manage")
        or (
            request.user.has_perm("workorders.update_assigned")
            and work_order.assigned_to_id == request.user.pk
        )
    ):
        raise PermissionDenied
    get_object_or_404(
        WorkOrderLine,
        pk=line_pk,
        work_order_id=work_order.pk,
    )
    try:
        remove_work_order_line(
            work_order_id=work_order.pk,
            line_id=line_pk,
            actor=request.user,
        )
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
    else:
        messages.success(request, "Línea retirada; quedó registrada en el historial.")
    return redirect(work_order)


@login_required
def order_update_assigned(request, pk):
    work_order = get_object_or_404(WorkOrder, pk=pk)
    if request.method != "POST":
        raise PermissionDenied
    if not (
        request.user.has_perm("workorders.update_assigned")
        and work_order.assigned_to_id == request.user.pk
    ):
        raise PermissionDenied
    form = TechnicianUpdateForm(request.POST)
    if form.is_valid():
        try:
            update_assigned_work(
                work_order_id=work_order.pk,
                actor=request.user,
                **form.cleaned_data,
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Diagnóstico actualizado.")
            return redirect(work_order)
    return render(
        request,
        "workorders/order_detail.html",
        _detail_context(
            request,
            work_order,
            technician_form=form,
        ),
    )


@login_required
def order_transition(request, pk):
    work_order = get_object_or_404(WorkOrder, pk=pk)
    if request.method != "POST":
        raise PermissionDenied
    form = TransitionForm(
        request.POST,
        work_order=work_order,
        actor=request.user,
    )
    if form.is_valid():
        try:
            transition_work_order(
                work_order_id=work_order.pk,
                new_status=form.cleaned_data["status"],
                actor=request.user,
            )
        except (ValidationError, PermissionDenied) as error:
            messages.error(
                request,
                "; ".join(error.messages)
                if isinstance(error, ValidationError)
                else str(error),
            )
        else:
            messages.success(request, "Estado de la orden actualizado.")
    else:
        messages.error(request, "Selecciona un estado permitido.")
    return redirect(work_order)


@login_required
def order_approve(request, pk):
    work_order = get_object_or_404(WorkOrder, pk=pk)
    if not request.user.has_perm("workorders.approve"):
        raise PermissionDenied
    if work_order.status != WorkOrder.Status.WAITING_APPROVAL:
        messages.error(request, "La orden no está esperando aprobación.")
        return redirect(work_order)
    form = ApprovalForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            approve_work_order(
                work_order_id=work_order.pk,
                actor=request.user,
                **form.cleaned_data,
            )
        except ValidationError as error:
            if hasattr(error, "message_dict"):
                for field, errors in error.message_dict.items():
                    for message in errors:
                        form.add_error(
                            field if field in form.fields else None,
                            message,
                        )
            else:
                form.add_error(None, error)
        else:
            messages.success(request, "Aprobación registrada.")
            return redirect(work_order)
    return render(
        request,
        "workorders/approval_form.html",
        {"form": form, "work_order": work_order},
    )


def _detail_context(request, work_order, *, line_form=None):
    can_manage = request.user.has_perm("workorders.manage")
    can_update_assigned = (
        request.user.has_perm("workorders.update_assigned")
        and work_order.assigned_to_id == request.user.pk
    )
    can_add_line = _can_add_line(request.user, work_order)
    can_update_work = (
        can_update_assigned
        and work_order.status
        in {WorkOrder.Status.DIAGNOSING, WorkOrder.Status.IN_PROGRESS}
    )
    return {
        "work_order": work_order,
        "can_manage": can_manage,
        "can_update_assigned": can_update_assigned,
        "can_change_details": can_manage and work_order.status in {
            WorkOrder.Status.DRAFT,
            WorkOrder.Status.RECEIVED,
            WorkOrder.Status.DIAGNOSING,
        },
        "can_add_line": can_add_line,
        "can_update_work": can_update_work,
        "technician_form": (
            TechnicianUpdateForm(
                initial={
                    "diagnosis": work_order.diagnosis,
                    "notes": work_order.notes,
                }
            )
            if can_update_work
            else None
        ),
        "can_see_prices": can_manage
        or request.user.has_perm("finance.payments.manage"),
        "line_form": line_form if line_form is not None else (
            WorkOrderLineForm() if can_add_line else None
        ),
        "transition_form": (
            TransitionForm(work_order=work_order, actor=request.user)
            if can_manage or can_update_assigned
            else None
        ),
        "can_approve": request.user.has_perm("workorders.approve")
        and work_order.status == WorkOrder.Status.WAITING_APPROVAL,
        "can_see_approval": request.user.has_perm("workorders.approve"),
    }
