from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import StaffUser
from customers.models import Customer, Motorcycle
from inventory.models import Service
from maintenance.forms import MaintenancePlanForm
from maintenance.models import MaintenancePlan, MaintenanceRecord, ReminderLog
from maintenance.services import (
    record_delivered_work_order,
    record_reminder_sent,
    schedule_reminder,
    update_reminder_status,
)
from workorders.models import CustomerApproval, WorkOrder, WorkOrderLine
from workorders.services import (
    add_work_order_line,
    approve_work_order,
    create_work_order,
    transition_work_order,
)


class MaintenanceTests(TestCase):
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
            current_mileage=1000,
        )
        self.service = Service.objects.create(
            name="Cambio de aceite",
            default_price=Decimal("45.00"),
        )
        self.plan = MaintenancePlan.objects.create(
            motorcycle=self.motorcycle,
            service_name="Cambio de aceite",
            last_completed_mileage=1000,
            due_mileage=2000,
            created_by=self.reception,
        )

    def create_delivered_order(self):
        order = create_work_order(
            data={
                "customer": self.customer,
                "motorcycle": self.motorcycle,
                "assigned_to": self.technician,
                "mileage": 1250,
                "complaint": "Servicio periódico.",
                "diagnosis": "Aceite y filtro reemplazados.",
                "notes": "",
            },
            actor=self.reception,
        )
        for status in (
            WorkOrder.Status.RECEIVED,
            WorkOrder.Status.DIAGNOSING,
        ):
            transition_work_order(
                work_order_id=order.pk,
                new_status=status,
                actor=self.reception,
            )
        add_work_order_line(
            work_order_id=order.pk,
            line_type=WorkOrderLine.LineType.SERVICE,
            item_id=self.service.pk,
            quantity=Decimal("1"),
            actor=self.reception,
        )
        transition_work_order(
            work_order_id=order.pk,
            new_status=WorkOrder.Status.WAITING_APPROVAL,
            actor=self.reception,
        )
        approve_work_order(
            work_order_id=order.pk,
            channel=CustomerApproval.Channel.PHONE,
            evidence_note="Aprobación por llamada.",
            actor=self.reception,
        )
        for status, actor in (
            (WorkOrder.Status.IN_PROGRESS, self.technician),
            (WorkOrder.Status.READY, self.technician),
            (WorkOrder.Status.DELIVERED, self.reception),
        ):
            transition_work_order(
                work_order_id=order.pk,
                new_status=status,
                actor=actor,
            )
        return order

    def test_due_date_and_mileage_raise_independent_alerts(self):
        self.plan.due_date = timezone.localdate() - timedelta(days=1)
        self.plan.save()
        self.assertTrue(self.plan.is_due)
        self.assertTrue(self.plan.date_is_due)
        self.assertFalse(self.plan.mileage_is_due)

        self.plan.due_date = timezone.localdate() + timedelta(days=10)
        self.plan.last_completed_mileage = 900
        self.plan.due_mileage = 1000
        self.plan.save()
        self.assertTrue(self.plan.is_due)
        self.assertFalse(self.plan.date_is_due)
        self.assertTrue(self.plan.mileage_is_due)

    def test_completed_and_cancelled_plans_do_not_alert(self):
        self.plan.due_date = timezone.localdate() - timedelta(days=1)
        self.plan.status = MaintenancePlan.Status.COMPLETED
        self.plan.save()
        self.assertFalse(self.plan.is_due)

        self.plan.status = MaintenancePlan.Status.CANCELLED
        self.plan.save()
        self.assertFalse(self.plan.is_due)

    def test_plan_requires_date_or_mileage_and_future_mileage_threshold(self):
        form_without_due = MaintenancePlanForm(
            data={
                "motorcycle": self.motorcycle.pk,
                "service_name": "Revisión general",
                "last_completed_at": "",
                "last_completed_mileage": "",
                "due_date": "",
                "due_mileage": "",
                "status": MaintenancePlan.Status.ACTIVE,
                "notes": "",
            }
        )
        self.assertFalse(form_without_due.is_valid())

        form_past_mileage = MaintenancePlanForm(
            data={
                "motorcycle": self.motorcycle.pk,
                "service_name": "Revisión general",
                "last_completed_at": "",
                "last_completed_mileage": "900",
                "due_date": "",
                "due_mileage": "1000",
                "status": MaintenancePlan.Status.ACTIVE,
                "notes": "",
            }
        )
        self.assertFalse(form_past_mileage.is_valid())
        self.assertIn("due_mileage", form_past_mileage.errors)

        inactive_plan = MaintenancePlanForm(
            data={
                "motorcycle": self.motorcycle.pk,
                "service_name": "Mantenimiento concluido",
                "last_completed_at": "",
                "last_completed_mileage": "900",
                "due_date": "",
                "due_mileage": "1000",
                "status": MaintenancePlan.Status.COMPLETED,
                "notes": "",
            }
        )
        self.assertTrue(inactive_plan.is_valid(), inactive_plan.errors)

    def test_delivery_creates_immutable_history_exactly_once(self):
        order = self.create_delivered_order()

        record = MaintenanceRecord.objects.get(work_order=order)
        self.assertEqual(record.motorcycle, self.motorcycle)
        self.assertEqual(record.mileage, 1250)
        self.assertIn("Aceite y filtro reemplazados.", record.summary)
        self.assertIn("Cambio de aceite", record.summary)

        same_record = record_delivered_work_order(work_order=order)
        self.assertEqual(same_record.pk, record.pk)
        self.assertEqual(MaintenanceRecord.objects.filter(work_order=order).count(), 1)

        with self.assertRaises(ValidationError):
            record.save()
        with self.assertRaises(ValidationError):
            record.delete()

    def test_history_only_accepts_delivered_orders(self):
        order = create_work_order(
            data={
                "customer": self.customer,
                "motorcycle": self.motorcycle,
                "assigned_to": self.technician,
                "mileage": 1100,
                "complaint": "Revisión.",
                "diagnosis": "Diagnóstico.",
                "notes": "",
            },
            actor=self.reception,
        )
        with self.assertRaises(ValidationError):
            record_delivered_work_order(work_order=order)
        self.assertFalse(
            MaintenanceRecord.objects.filter(work_order=order).exists()
        )

    def test_reminders_are_deduplicated_by_plan_channel_and_date(self):
        scheduled_for = timezone.localdate() + timedelta(days=1)
        reminder = schedule_reminder(
            plan_id=self.plan.pk,
            channel=ReminderLog.Channel.TELEGRAM,
            scheduled_for=scheduled_for,
            actor=self.reception,
            note="Aviso de mantenimiento pendiente.",
        )
        with self.assertRaises(ValidationError):
            schedule_reminder(
                plan_id=self.plan.pk,
                channel=ReminderLog.Channel.TELEGRAM,
                scheduled_for=scheduled_for,
                actor=self.admin,
            )

        other_channel = schedule_reminder(
            plan_id=self.plan.pk,
            channel=ReminderLog.Channel.PHONE,
            scheduled_for=scheduled_for,
            actor=self.reception,
        )
        self.assertNotEqual(reminder.pk, other_channel.pk)
        self.assertEqual(self.plan.reminders.count(), 2)

    def test_reminder_service_enforces_role_permission(self):
        with self.assertRaises(ValidationError):
            schedule_reminder(
                plan_id=self.plan.pk,
                channel=ReminderLog.Channel.TELEGRAM,
                scheduled_for=timezone.localdate(),
                actor=self.technician,
            )

    def test_sent_reminder_requires_explicit_manual_record_and_is_immutable(self):
        reminder = schedule_reminder(
            plan_id=self.plan.pk,
            channel=ReminderLog.Channel.TELEGRAM,
            scheduled_for=timezone.localdate(),
            actor=self.reception,
        )
        sent = record_reminder_sent(
            reminder_id=reminder.pk,
            actor=self.reception,
            note="Envío realizado manualmente por Telegram.",
        )
        self.assertEqual(sent.status, ReminderLog.Status.SENT)
        self.assertEqual(sent.sent_by, self.reception)
        self.assertIsNotNone(sent.sent_at)

        with self.assertRaises(ValidationError):
            record_reminder_sent(
                reminder_id=reminder.pk,
                actor=self.reception,
                note="Intento repetido.",
            )
        sent.note = "alteración"
        with self.assertRaises(ValidationError):
            sent.save()

    def test_pending_reminder_can_be_cancelled_or_marked_failed_once(self):
        reminder = schedule_reminder(
            plan_id=self.plan.pk,
            channel=ReminderLog.Channel.PHONE,
            scheduled_for=timezone.localdate(),
            actor=self.reception,
        )
        updated = update_reminder_status(
            reminder_id=reminder.pk,
            status=ReminderLog.Status.CANCELLED,
            actor=self.admin,
            note="Cliente pidió no recibir el aviso.",
        )
        self.assertEqual(updated.status, ReminderLog.Status.CANCELLED)
        self.assertEqual(updated.updated_by, self.admin)

        with self.assertRaises(ValidationError):
            update_reminder_status(
                reminder_id=reminder.pk,
                status=ReminderLog.Status.FAILED,
                actor=self.admin,
            )

    def test_only_reception_and_admin_can_access_maintenance(self):
        self.client.force_login(self.technician)
        self.assertEqual(
            self.client.get(reverse("maintenance:index")).status_code,
            403,
        )
        self.client.force_login(self.cashier)
        self.assertEqual(
            self.client.get(reverse("maintenance:index")).status_code,
            403,
        )

        self.client.force_login(self.reception)
        self.assertEqual(
            self.client.get(reverse("maintenance:index")).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("maintenance:plan_create")).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                reverse("maintenance:plan_detail", args=[self.plan.pk])
            ).status_code,
            200,
        )

    def test_reception_can_create_plan_and_manual_reminder(self):
        self.client.force_login(self.reception)
        response = self.client.post(
            reverse("maintenance:plan_create"),
            {
                "motorcycle": self.motorcycle.pk,
                "service_name": "Cambio de filtro",
                "last_completed_at": "",
                "last_completed_mileage": "1000",
                "due_date": "",
                "due_mileage": "3000",
                "status": MaintenancePlan.Status.ACTIVE,
                "notes": "",
            },
        )
        plan = MaintenancePlan.objects.get(service_name="Cambio de filtro")
        self.assertRedirects(response, plan.get_absolute_url())

        response = self.client.post(
            reverse("maintenance:reminder_create", args=[plan.pk]),
            {
                "channel": ReminderLog.Channel.TELEGRAM,
                "scheduled_for": (
                    timezone.localdate() + timedelta(days=2)
                ).isoformat(),
                "note": "Enviar recordatorio.",
            },
        )
        self.assertRedirects(response, plan.get_absolute_url())
        self.assertEqual(plan.reminders.count(), 1)

    def test_duplicate_reminder_web_submission_shows_validation_error(self):
        scheduled_for = timezone.localdate() + timedelta(days=3)
        schedule_reminder(
            plan_id=self.plan.pk,
            channel=ReminderLog.Channel.TELEGRAM,
            scheduled_for=scheduled_for,
            actor=self.reception,
        )
        self.client.force_login(self.reception)
        response = self.client.post(
            reverse("maintenance:reminder_create", args=[self.plan.pk]),
            {
                "channel": ReminderLog.Channel.TELEGRAM,
                "scheduled_for": scheduled_for.isoformat(),
                "note": "Duplicado.",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ya existe un recordatorio")
        self.assertEqual(self.plan.reminders.count(), 1)

    def test_reminder_mark_sent_is_manual_and_requires_evidence(self):
        reminder = schedule_reminder(
            plan_id=self.plan.pk,
            channel=ReminderLog.Channel.TELEGRAM,
            scheduled_for=timezone.localdate(),
            actor=self.reception,
        )
        self.client.force_login(self.reception)

        invalid = self.client.post(
            reverse("maintenance:reminder_mark_sent", args=[reminder.pk]),
            {"note": " "},
        )
        self.assertRedirects(invalid, self.plan.get_absolute_url())
        reminder.refresh_from_db()
        self.assertEqual(reminder.status, ReminderLog.Status.PENDING)

        valid = self.client.post(
            reverse("maintenance:reminder_mark_sent", args=[reminder.pk]),
            {"note": "Se envió manualmente."},
        )
        self.assertRedirects(valid, self.plan.get_absolute_url())
        reminder.refresh_from_db()
        self.assertEqual(reminder.status, ReminderLog.Status.SENT)
        self.assertContains(
            self.client.get(self.plan.get_absolute_url()),
            "La aplicación solo registra el recordatorio",
        )
