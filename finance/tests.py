from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import StaffUser
from customers.models import Customer, Motorcycle
from finance.models import CashSession, Expense, Payment
from finance.services import (
    close_cash_session,
    open_cash_session,
    record_expense,
    record_payment,
)
from inventory.models import Service
from workorders.models import CustomerApproval, WorkOrder, WorkOrderLine
from workorders.services import (
    add_work_order_line,
    approve_work_order,
    create_work_order,
    transition_work_order,
)


class FinanceTests(TestCase):
    def setUp(self):
        self.admin = StaffUser.objects.create_user(
            username="admin",
            role=StaffUser.Role.ADMINISTRATOR,
        )
        self.cashier = StaffUser.objects.create_user(
            username="cajero",
            role=StaffUser.Role.CASHIER,
        )
        self.other_cashier = StaffUser.objects.create_user(
            username="otro_cajero",
            role=StaffUser.Role.CASHIER,
        )
        self.reception = StaffUser.objects.create_user(
            username="recepcion",
            role=StaffUser.Role.RECEPTION,
        )
        self.technician = StaffUser.objects.create_user(
            username="tecnico",
            role=StaffUser.Role.TECHNICIAN,
        )
        self.customer = Customer.objects.create(
            full_name="Luis Pérez",
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
            name="Servicio de prueba",
            default_price=Decimal("100.00"),
        )
        self.order = self.create_ready_order()

    def create_ready_order(self):
        order = create_work_order(
            data={
                "customer": self.customer,
                "motorcycle": self.motorcycle,
                "assigned_to": self.technician,
                "mileage": 1100,
                "complaint": "Servicio periódico.",
                "diagnosis": "Mantenimiento realizado.",
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
            evidence_note="Aprobado por llamada.",
            actor=self.reception,
        )
        transition_work_order(
            work_order_id=order.pk,
            new_status=WorkOrder.Status.IN_PROGRESS,
            actor=self.technician,
        )
        transition_work_order(
            work_order_id=order.pk,
            new_status=WorkOrder.Status.READY,
            actor=self.technician,
        )
        return order

    def open_session(self, *, actor=None, amount="20.00"):
        return open_cash_session(
            opening_cash=Decimal(amount),
            actor=actor or self.cashier,
        )

    def payment(self, *, session, amount, method=Payment.Method.CASH):
        return record_payment(
            session_id=session.pk,
            work_order_id=self.order.pk,
            amount=Decimal(amount),
            method=method,
            actor=self.cashier,
        )

    def test_only_one_cash_session_can_be_open_and_opening_is_audited(self):
        session = self.open_session()

        with self.assertRaises(ValidationError):
            self.open_session(actor=self.other_cashier)
        with self.assertRaises(ValidationError):
            self.open_session(amount="-1.00")

        self.assertEqual(session.opened_by, self.cashier)
        self.assertTrue(session.is_open)
        self.assertEqual(CashSession.objects.filter(closed_at__isnull=True).count(), 1)

    def test_cashier_cannot_operate_another_cashiers_session(self):
        session = self.open_session()

        with self.assertRaises(PermissionDenied):
            close_cash_session(
                session_id=session.pk,
                counted_cash=Decimal("20.00"),
                actor=self.other_cashier,
            )

        closed = close_cash_session(
            session_id=session.pk,
            counted_cash=Decimal("20.00"),
            actor=self.admin,
        )
        self.assertEqual(closed.closed_by, self.admin)

    def test_partial_payments_cannot_exceed_order_balance(self):
        session = self.open_session()
        first = self.payment(session=session, amount="40.00")
        self.assertEqual(first.amount, Decimal("40.00"))

        with self.assertRaises(ValidationError):
            self.payment(session=session, amount="60.01")

        second = self.payment(
            session=session,
            amount="60.00",
            method=Payment.Method.YAPE,
        )
        self.assertEqual(second.work_order, self.order)
        with self.assertRaises(ValidationError):
            self.payment(session=session, amount="0.01")

    def test_payment_rejects_orders_that_are_not_ready(self):
        session = self.open_session()
        order = create_work_order(
            data={
                "customer": self.customer,
                "motorcycle": self.motorcycle,
                "assigned_to": self.technician,
                "mileage": 1100,
                "complaint": "Otro servicio.",
                "diagnosis": "",
                "notes": "",
            },
            actor=self.reception,
        )

        with self.assertRaises(ValidationError):
            record_payment(
                session_id=session.pk,
                work_order_id=order.pk,
                amount=Decimal("1.00"),
                method=Payment.Method.CASH,
                actor=self.cashier,
            )

    def test_cash_reconciliation_includes_only_cash_movements(self):
        session = self.open_session(amount="20.00")
        self.payment(session=session, amount="30.00")
        self.payment(
            session=session,
            amount="20.00",
            method=Payment.Method.PLIN,
        )
        record_expense(
            session_id=session.pk,
            category=Expense.Category.SUPPLIES,
            description="Compra menor",
            amount=Decimal("10.00"),
            method=Payment.Method.CASH,
            actor=self.cashier,
        )
        record_expense(
            session_id=session.pk,
            category=Expense.Category.TRANSPORT,
            description="Taxi",
            amount=Decimal("5.00"),
            method=Payment.Method.CARD,
            actor=self.cashier,
        )

        closed = close_cash_session(
            session_id=session.pk,
            counted_cash=Decimal("39.00"),
            actor=self.cashier,
        )
        self.assertEqual(closed.expected_cash, Decimal("40.00"))
        self.assertEqual(closed.difference_cash, Decimal("-1.00"))
        self.assertEqual(closed.closed_by, self.cashier)

        with self.assertRaises(ValidationError):
            record_expense(
                session_id=session.pk,
                category=Expense.Category.OTHER,
                description="No permitido",
                amount=Decimal("1.00"),
                method=Payment.Method.CASH,
                actor=self.cashier,
            )

    def test_cash_expense_cannot_exceed_cash_available(self):
        session = self.open_session(amount="5.00")
        with self.assertRaises(ValidationError):
            record_expense(
                session_id=session.pk,
                category=Expense.Category.SUPPLIES,
                description="Compra mayor al efectivo",
                amount=Decimal("5.01"),
                method=Payment.Method.CASH,
                actor=self.cashier,
            )

    def test_financial_records_are_immutable(self):
        session = self.open_session()
        payment = self.payment(session=session, amount="10.00")
        with self.assertRaises(ValidationError):
            payment.save()
        with self.assertRaises(ValidationError):
            payment.delete()

        expense = record_expense(
            session_id=session.pk,
            category=Expense.Category.OTHER,
            description="Gasto",
            amount=Decimal("1.00"),
            method=Payment.Method.CASH,
            actor=self.cashier,
        )
        with self.assertRaises(ValidationError):
            expense.save()
        with self.assertRaises(ValidationError):
            expense.delete()

    def test_views_enforce_cash_and_report_permissions(self):
        self.client.force_login(self.reception)
        self.assertEqual(self.client.get(reverse("finance:index")).status_code, 403)
        self.assertEqual(self.client.get(reverse("finance:reports")).status_code, 403)

        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(reverse("finance:index")).status_code, 200)
        report_response = self.client.get(reverse("finance:reports"))
        self.assertEqual(report_response.status_code, 200)
        self.assertIsNotNone(report_response.context["report"])
        self.assertEqual(
            self.client.post(reverse("finance:open"), {"opening_cash": "15.00"}).status_code,
            302,
        )
        self.assertEqual(CashSession.objects.count(), 1)

    def test_report_summarizes_amounts_by_method_and_period(self):
        session = self.open_session()
        self.payment(session=session, amount="25.00")
        self.payment(
            session=session,
            amount="15.00",
            method=Payment.Method.YAPE,
        )
        record_expense(
            session_id=session.pk,
            category=Expense.Category.OTHER,
            description="Gasto de prueba",
            amount=Decimal("5.00"),
            method=Payment.Method.CASH,
            actor=self.cashier,
        )
        close_cash_session(
            session_id=session.pk,
            counted_cash=Decimal("40.00"),
            actor=self.cashier,
        )

        self.client.force_login(self.cashier)
        today = timezone.localdate().isoformat()
        response = self.client.get(
            reverse("finance:reports"),
            {"start_date": today, "end_date": today},
        )
        self.assertEqual(response.status_code, 200)
        report = response.context["report"]
        self.assertEqual(report["payment_total"], Decimal("40.00"))
        self.assertEqual(report["expense_total"], Decimal("5.00"))
        self.assertEqual(report["net_total"], Decimal("35.00"))
        self.assertContains(response, "Yape")
        self.assertContains(response, "Cierres de caja")

    def test_report_rejects_reversed_date_range(self):
        self.client.force_login(self.cashier)
        start = timezone.localdate()
        response = self.client.get(
            reverse("finance:reports"),
            {
                "start_date": (start + timedelta(days=1)).isoformat(),
                "end_date": start.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["report"])
