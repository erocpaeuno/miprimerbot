from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import StaffUser
from customers.models import Customer, Motorcycle
from inventory.models import InventoryMovement, Part, Service
from workorders.forms import WorkOrderForm
from workorders.models import (
    CustomerApproval,
    WorkOrder,
    WorkOrderEvent,
    WorkOrderLine,
)
from workorders.services import (
    add_work_order_line,
    approve_work_order,
    create_work_order,
    transition_work_order,
    update_work_order,
)


class WorkOrderTests(TestCase):
    def setUp(self):
        self.admin = StaffUser.objects.create_user(
            username="admin",
            role=StaffUser.Role.ADMINISTRATOR,
        )
        self.reception = StaffUser.objects.create_user(
            username="recepcion",
            role=StaffUser.Role.RECEPTION,
        )
        self.technician = StaffUser.objects.create_user(
            username="tecnico",
            role=StaffUser.Role.TECHNICIAN,
        )
        self.other_technician = StaffUser.objects.create_user(
            username="tecnico2",
            role=StaffUser.Role.TECHNICIAN,
        )
        self.cashier = StaffUser.objects.create_user(
            username="caja",
            role=StaffUser.Role.CASHIER,
        )
        self.customer = Customer.objects.create(
            full_name="María Quispe",
            phone="999123456",
        )
        self.motorcycle = Motorcycle.objects.create(
            customer=self.customer,
            plate="ABC-123",
            make="Honda",
            model="CB 190R",
            current_mileage=1250,
        )
        self.service = Service.objects.create(
            name="Cambio de aceite",
            default_price=Decimal("45.00"),
            estimated_minutes=30,
        )
        self.part = Part.objects.create(
            sku="ACEITE-10W40",
            name="Aceite 10W-40",
            unit="litro",
            unit_price=Decimal("35.50"),
        )
        self.work_order = self.create_order()

    def create_order(self, *, assigned_to=None):
        if assigned_to is None:
            assigned_to = self.technician
        return create_work_order(
            data={
                "customer": self.customer,
                "motorcycle": self.motorcycle,
                "assigned_to": assigned_to,
                "mileage": 1250,
                "complaint": "Revisar ruido en el motor.",
                "diagnosis": "Revisión inicial del sistema de motor.",
                "notes": "",
            },
            actor=self.reception,
        )

    def advance_to_diagnosing(self, work_order=None):
        work_order = work_order or self.work_order
        work_order.refresh_from_db()
        transition_work_order(
            work_order_id=work_order.pk,
            new_status=WorkOrder.Status.RECEIVED,
            actor=self.reception,
        )
        return transition_work_order(
            work_order_id=work_order.pk,
            new_status=WorkOrder.Status.DIAGNOSING,
            actor=self.reception,
        )

    def advance_to_approval(self, work_order=None):
        work_order = work_order or self.work_order
        work_order.refresh_from_db()
        if work_order.status not in {
            WorkOrder.Status.DIAGNOSING,
            WorkOrder.Status.WAITING_APPROVAL,
        }:
            work_order = self.advance_to_diagnosing(work_order)
        if work_order.status == WorkOrder.Status.WAITING_APPROVAL:
            return work_order
        if not work_order.lines.exists():
            add_work_order_line(
                work_order_id=work_order.pk,
                line_type=WorkOrderLine.LineType.SERVICE,
                item_id=self.service.pk,
                quantity=Decimal("1"),
                actor=self.reception,
            )
        return transition_work_order(
            work_order_id=work_order.pk,
            new_status=WorkOrder.Status.WAITING_APPROVAL,
            actor=self.reception,
        )

    def approve(self, work_order=None):
        work_order = work_order or self.work_order
        work_order.refresh_from_db()
        if work_order.status != WorkOrder.Status.WAITING_APPROVAL:
            self.advance_to_approval(work_order)
        return approve_work_order(
            work_order_id=work_order.pk,
            channel=CustomerApproval.Channel.TELEGRAM_MANUAL,
            evidence_note="Cliente confirmó por Telegram; anotado manualmente.",
            actor=self.reception,
        )

    def test_create_order_generates_number_and_audit_event(self):
        self.assertTrue(self.work_order.order_number.startswith("OT-"))
        self.assertEqual(self.work_order.status, WorkOrder.Status.DRAFT)
        event = self.work_order.events.get()
        self.assertEqual(event.event_type, WorkOrderEvent.EventType.CREATED)
        self.assertEqual(event.actor, self.reception)

    def test_order_form_requires_motorcycle_owned_by_selected_customer(self):
        other_customer = Customer.objects.create(
            full_name="Juan Pérez",
            phone="988123456",
        )
        form = WorkOrderForm(
            data={
                "customer": other_customer.pk,
                "motorcycle": self.motorcycle.pk,
                "assigned_to": "",
                "mileage": "1250",
                "complaint": "Revisión",
                "diagnosis": "",
                "notes": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("motorcycle", form.errors)

    def test_order_form_rejects_mileage_below_latest_motorcycle_reading(self):
        form = WorkOrderForm(
            data={
                "customer": self.customer.pk,
                "motorcycle": self.motorcycle.pk,
                "assigned_to": self.technician.pk,
                "mileage": "1249",
                "complaint": "Revisión",
                "diagnosis": "",
                "notes": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("mileage", form.errors)

    def test_catalog_prices_and_descriptions_are_snapshotted(self):
        line = add_work_order_line(
            work_order_id=self.work_order.pk,
            line_type=WorkOrderLine.LineType.SERVICE,
            item_id=self.service.pk,
            quantity=Decimal("1"),
            actor=self.reception,
        )
        self.service.name = "Precio de catálogo actualizado"
        self.service.default_price = Decimal("99.00")
        self.service.save()

        line.refresh_from_db()
        self.assertEqual(line.description_snapshot, "Cambio de aceite")
        self.assertEqual(line.unit_price, Decimal("45.00"))
        self.assertEqual(line.line_total, Decimal("45.00"))
        self.assertEqual(self.work_order.total, Decimal("45.00"))
        with self.assertRaises(ValidationError):
            line.save()

    def test_order_line_amounts_are_rounded_to_currency_precision(self):
        line = add_work_order_line(
            work_order_id=self.work_order.pk,
            line_type=WorkOrderLine.LineType.PART,
            item_id=self.part.pk,
            quantity=Decimal("1.5"),
            actor=self.reception,
        )

        self.assertEqual(line.line_total, Decimal("53.25"))
        self.assertEqual(self.work_order.total, Decimal("53.25"))

    def test_order_and_line_creation_views_use_server_catalog_price(self):
        self.client.force_login(self.reception)
        created = self.client.post(
            reverse("workorders:create"),
            {
                "customer": self.customer.pk,
                "motorcycle": self.motorcycle.pk,
                "assigned_to": self.technician.pk,
                "mileage": "1250",
                "complaint": "Revisar transmisión.",
                "diagnosis": "Ajustar transmisión.",
                "notes": "",
            },
        )
        work_order = WorkOrder.objects.exclude(pk=self.work_order.pk).get()
        self.assertRedirects(created, work_order.get_absolute_url())

        added = self.client.post(
            reverse("workorders:add_line", args=[work_order.pk]),
            {
                "line_type": WorkOrderLine.LineType.SERVICE,
                "service": self.service.pk,
                "part": "",
                "quantity": "1",
                "unit_price": "0.01",
            },
        )
        self.assertRedirects(added, work_order.get_absolute_url())
        line = work_order.lines.get()
        self.assertEqual(line.unit_price, Decimal("45.00"))

    def test_assigned_technician_can_update_diagnosis_and_audit_it(self):
        work_order = self.create_order()
        self.advance_to_diagnosing(work_order)
        self.client.force_login(self.technician)

        response = self.client.post(
            reverse("workorders:update_assigned", args=[work_order.pk]),
            {
                "diagnosis": "Cadena requiere ajuste.",
                "notes": "Verificar tensión antes de entregar.",
            },
        )

        self.assertRedirects(response, work_order.get_absolute_url())
        work_order.refresh_from_db()
        self.assertEqual(work_order.diagnosis, "Cadena requiere ajuste.")
        event = work_order.events.get(
            event_type=WorkOrderEvent.EventType.DETAILS_UPDATED
        )
        self.assertEqual(event.actor, self.technician)

    def test_general_order_edits_are_audited_without_copying_private_values(self):
        data = {
            "customer": self.customer,
            "motorcycle": self.motorcycle,
            "assigned_to": self.other_technician,
            "mileage": 1250,
            "complaint": "Motivo actualizado.",
            "diagnosis": self.work_order.diagnosis,
            "notes": "Nota confidencial actualizada.",
        }
        update_work_order(
            work_order_id=self.work_order.pk,
            data=data,
            actor=self.reception,
        )
        event = self.work_order.events.get(
            event_type=WorkOrderEvent.EventType.DETAILS_UPDATED
        )

        self.assertIn("complaint", event.description)
        self.assertIn("assigned_to", event.description)
        self.assertNotIn("Nota confidencial", event.description)

    def test_parts_are_deducted_atomically_when_work_starts(self):
        self.part.stock = Decimal("2.000")
        self.part.save()
        self.advance_to_diagnosing()
        add_work_order_line(
            work_order_id=self.work_order.pk,
            line_type=WorkOrderLine.LineType.PART,
            item_id=self.part.pk,
            quantity=Decimal("1.5"),
            actor=self.reception,
        )
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock, Decimal("2.000"))

        self.transition_to_waiting_approval()
        self.approve(self.work_order)
        transition_work_order(
            work_order_id=self.work_order.pk,
            new_status=WorkOrder.Status.IN_PROGRESS,
            actor=self.technician,
        )

        self.part.refresh_from_db()
        line = self.work_order.lines.get(line_type=WorkOrderLine.LineType.PART)
        movement = InventoryMovement.objects.get(work_order=self.work_order)
        self.assertEqual(self.part.stock, Decimal("0.500"))
        self.assertTrue(line.stock_deducted)
        self.assertEqual(movement.movement_type, InventoryMovement.MovementType.EXIT)
        self.assertEqual(movement.quantity, Decimal("1.500"))

    def transition_to_waiting_approval(self):
        return transition_work_order(
            work_order_id=self.work_order.pk,
            new_status=WorkOrder.Status.WAITING_APPROVAL,
            actor=self.reception,
        )

    def test_insufficient_stock_rolls_back_start_and_inventory_movement(self):
        self.advance_to_diagnosing()
        add_work_order_line(
            work_order_id=self.work_order.pk,
            line_type=WorkOrderLine.LineType.PART,
            item_id=self.part.pk,
            quantity=Decimal("1"),
            actor=self.reception,
        )
        self.transition_to_waiting_approval()
        self.approve(self.work_order)

        with self.assertRaises(ValidationError):
            transition_work_order(
                work_order_id=self.work_order.pk,
                new_status=WorkOrder.Status.IN_PROGRESS,
                actor=self.technician,
            )

        self.work_order.refresh_from_db()
        self.part.refresh_from_db()
        self.assertEqual(self.work_order.status, WorkOrder.Status.APPROVED)
        self.assertEqual(self.part.stock, Decimal("0"))
        self.assertFalse(
            InventoryMovement.objects.filter(work_order=self.work_order).exists()
        )
        self.assertFalse(
            self.work_order.lines.get(
                line_type=WorkOrderLine.LineType.PART
            ).stock_deducted
        )

    def test_manual_approval_is_required_before_starting_work(self):
        self.advance_to_approval()
        with self.assertRaises(ValidationError):
            transition_work_order(
                work_order_id=self.work_order.pk,
                new_status=WorkOrder.Status.IN_PROGRESS,
                actor=self.reception,
            )

        approved = approve_work_order(
            work_order_id=self.work_order.pk,
            channel=CustomerApproval.Channel.PHONE,
            evidence_note="Confirmación recibida por llamada.",
            actor=self.reception,
        )
        self.assertEqual(approved.status, WorkOrder.Status.APPROVED)
        self.assertEqual(approved.customer_approval.recorded_by, self.reception)
        self.assertEqual(
            approved.events.filter(
                event_type=WorkOrderEvent.EventType.APPROVAL
            ).count(),
            1,
        )

    def test_cannot_request_approval_without_diagnosis_or_quote_lines(self):
        self.work_order.diagnosis = ""
        self.work_order.save(update_fields=["diagnosis"])
        transition_work_order(
            work_order_id=self.work_order.pk,
            new_status=WorkOrder.Status.RECEIVED,
            actor=self.reception,
        )
        transition_work_order(
            work_order_id=self.work_order.pk,
            new_status=WorkOrder.Status.DIAGNOSING,
            actor=self.reception,
        )

        with self.assertRaises(ValidationError):
            transition_work_order(
                work_order_id=self.work_order.pk,
                new_status=WorkOrder.Status.WAITING_APPROVAL,
                actor=self.reception,
            )

        self.work_order.refresh_from_db()
        self.work_order.diagnosis = "Revisión del sistema."
        self.work_order.save(update_fields=["diagnosis"])
        with self.assertRaises(ValidationError):
            transition_work_order(
                work_order_id=self.work_order.pk,
                new_status=WorkOrder.Status.WAITING_APPROVAL,
                actor=self.reception,
            )

    def test_invalid_skipped_transition_and_direct_status_edit_are_rejected(self):
        with self.assertRaises(ValidationError):
            transition_work_order(
                work_order_id=self.work_order.pk,
                new_status=WorkOrder.Status.DELIVERED,
                actor=self.reception,
            )

        self.work_order.status = WorkOrder.Status.DELIVERED
        with self.assertRaises(ValidationError):
            self.work_order.save()

    def test_technician_only_sees_and_changes_assigned_orders(self):
        assigned_order = self.create_order(assigned_to=self.technician)
        unassigned_order = self.create_order(assigned_to=self.other_technician)
        self.client.force_login(self.technician)

        listing = self.client.get(reverse("workorders:list"))
        self.assertContains(listing, assigned_order.order_number)
        self.assertNotContains(listing, unassigned_order.order_number)
        self.assertEqual(
            self.client.get(
                reverse("workorders:detail", args=[unassigned_order.pk])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("workorders:create")).status_code,
            403,
        )

    def test_technician_transition_rules_and_assignment_are_enforced(self):
        assigned_order = self.create_order(assigned_to=self.technician)
        self.advance_to_diagnosing(assigned_order)
        add_work_order_line(
            work_order_id=assigned_order.pk,
            line_type=WorkOrderLine.LineType.SERVICE,
            item_id=self.service.pk,
            quantity=Decimal("1"),
            actor=self.technician,
        )

        with self.assertRaises(PermissionDenied):
            transition_work_order(
                work_order_id=assigned_order.pk,
                new_status=WorkOrder.Status.CANCELLED,
                actor=self.technician,
            )
        with self.assertRaises(PermissionDenied):
            transition_work_order(
                work_order_id=assigned_order.pk,
                new_status=WorkOrder.Status.WAITING_APPROVAL,
                actor=self.other_technician,
            )

        result = transition_work_order(
            work_order_id=assigned_order.pk,
            new_status=WorkOrder.Status.WAITING_APPROVAL,
            actor=self.technician,
        )
        self.assertEqual(result.status, WorkOrder.Status.WAITING_APPROVAL)

    def test_only_admin_or_reception_can_register_approval(self):
        self.advance_to_approval()

        with self.assertRaises(PermissionDenied):
            approve_work_order(
                work_order_id=self.work_order.pk,
                channel=CustomerApproval.Channel.PHONE,
                evidence_note="Confirmación",
                actor=self.technician,
            )
        with self.assertRaises(ValidationError):
            approve_work_order(
                work_order_id=self.work_order.pk,
                channel=CustomerApproval.Channel.PHONE,
                evidence_note=" ",
                actor=self.reception,
            )
        self.assertFalse(
            CustomerApproval.objects.filter(work_order=self.work_order).exists()
        )

    def test_line_added_during_work_immediately_consumes_stock(self):
        self.part.stock = Decimal("2")
        self.part.save()
        self.approve()
        transition_work_order(
            work_order_id=self.work_order.pk,
            new_status=WorkOrder.Status.IN_PROGRESS,
            actor=self.technician,
        )

        line = add_work_order_line(
            work_order_id=self.work_order.pk,
            line_type=WorkOrderLine.LineType.PART,
            item_id=self.part.pk,
            quantity=Decimal("1"),
            actor=self.technician,
        )

        self.part.refresh_from_db()
        self.assertEqual(self.part.stock, Decimal("1.000"))
        self.assertTrue(line.stock_deducted)
        self.assertEqual(
            InventoryMovement.objects.filter(work_order=self.work_order).count(),
            1,
        )

    def test_quote_lines_can_be_removed_with_audit_before_approval(self):
        line = add_work_order_line(
            work_order_id=self.work_order.pk,
            line_type=WorkOrderLine.LineType.SERVICE,
            item_id=self.service.pk,
            quantity=Decimal("1"),
            actor=self.reception,
        )
        response = self.client
        response.force_login(self.reception)
        result = response.post(
            reverse(
                "workorders:remove_line",
                args=[self.work_order.pk, line.pk],
            )
        )

        self.assertRedirects(result, self.work_order.get_absolute_url())
        self.assertFalse(WorkOrderLine.objects.filter(pk=line.pk).exists())
        event = self.work_order.events.get(
            event_type=WorkOrderEvent.EventType.LINE_REMOVED
        )
        self.assertIn("Cambio de aceite", event.description)

    def test_quote_cannot_change_while_waiting_for_customer_approval(self):
        self.advance_to_approval()
        response = self.client
        response.force_login(self.reception)
        result = response.post(
            reverse("workorders:add_line", args=[self.work_order.pk]),
            {
                "line_type": WorkOrderLine.LineType.SERVICE,
                "service": self.service.pk,
                "part": "",
                "quantity": "1",
            },
        )

        self.assertEqual(result.status_code, 403)
        self.assertEqual(self.work_order.lines.count(), 1)

    def test_completed_order_flow_and_close_timestamp(self):
        self.approve()
        transition_work_order(
            work_order_id=self.work_order.pk,
            new_status=WorkOrder.Status.IN_PROGRESS,
            actor=self.technician,
        )
        transition_work_order(
            work_order_id=self.work_order.pk,
            new_status=WorkOrder.Status.READY,
            actor=self.technician,
        )
        delivered = transition_work_order(
            work_order_id=self.work_order.pk,
            new_status=WorkOrder.Status.DELIVERED,
            actor=self.reception,
        )
        self.assertIsNotNone(delivered.closed_at)
        self.assertEqual(
            delivered.status,
            WorkOrder.Status.DELIVERED,
        )

    def test_customer_approval_and_order_events_are_immutable(self):
        self.approve()
        approval = self.work_order.customer_approval
        event = self.work_order.events.first()

        with self.assertRaises(ValidationError):
            approval.delete()
        with self.assertRaises(ValidationError):
            event.delete()

    def test_cashier_can_view_orders_but_cannot_manage_or_approve(self):
        self.approve()
        self.client.force_login(self.cashier)

        self.assertEqual(self.client.get(reverse("workorders:list")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("workorders:create")).status_code,
            403,
        )
        detail = self.client.get(
            reverse("workorders:detail", args=[self.work_order.pk])
        )
        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(
            detail,
            "Cliente confirmó por Telegram; anotado manualmente.",
        )
