from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import StaffUser
from customers.forms import CustomerForm, MotorcycleForm
from customers.models import (
    Customer,
    CustomerPortalCode,
    Motorcycle,
    customer_portal_code_digest,
)
from inventory.models import Service
from workorders.models import (
    CustomerApproval,
    WorkOrder,
    WorkOrderEvent,
    WorkOrderLine,
)


class CustomerAndMotorcycleTests(TestCase):
    def setUp(self):
        self.reception = StaffUser.objects.create_user(
            username="recepcion",
            role=StaffUser.Role.RECEPTION,
        )
        self.customer = Customer.objects.create(
            full_name="María Quispe",
            phone="999123456",
        )

    def test_customer_pages_require_authentication(self):
        response = self.client.get(reverse("customers:customer_list"))

        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('customers:customer_list')}",
        )

    def test_reception_can_create_customer_and_dni_is_validated(self):
        self.client.force_login(self.reception)
        response = self.client.post(
            reverse("customers:customer_create"),
            {
                "full_name": "Juan Pérez",
                "dni": "12345678",
                "phone": "987654321",
                "email": "",
                "notes": "",
            },
        )

        customer = Customer.objects.get(dni="12345678")
        self.assertRedirects(response, customer.get_absolute_url())
        self.assertEqual(customer.full_name, "Juan Pérez")

        invalid = CustomerForm(
            data={
                "full_name": "DNI Inválido",
                "dni": "1234",
                "phone": "987654321",
            }
        )
        self.assertFalse(invalid.is_valid())
        self.assertIn("dni", invalid.errors)

    def test_dni_is_optional_but_unique_when_provided(self):
        existing = Customer.objects.create(
            full_name="Ana Ramos",
            dni="12345678",
            phone="988123456",
        )
        duplicate = CustomerForm(
            data={
                "full_name": "Otra persona",
                "dni": existing.dni,
                "phone": "977123456",
            }
        )

        self.assertFalse(duplicate.is_valid())
        self.assertIn("dni", duplicate.errors)
        self.assertIsNone(self.customer.dni)

    def test_technician_cannot_view_customer_or_motorcycle_pages(self):
        technician = StaffUser.objects.create_user(
            username="tecnico",
            role=StaffUser.Role.TECHNICIAN,
        )
        self.client.force_login(technician)

        customer_response = self.client.get(reverse("customers:customer_list"))
        motorcycle_response = self.client.get(
            reverse("customers:motorcycle_list")
        )

        self.assertEqual(customer_response.status_code, 403)
        self.assertEqual(motorcycle_response.status_code, 403)

    def test_reception_can_register_and_search_motorcycles(self):
        self.client.force_login(self.reception)
        form_page = self.client.get(
            reverse("customers:motorcycle_create"),
            {"customer": self.customer.pk},
        )
        self.assertContains(
            form_page,
            f'<option value="{self.customer.pk}" selected>',
            html=False,
        )
        response = self.client.post(
            reverse("customers:motorcycle_create"),
            {
                "customer": self.customer.pk,
                "plate": "abc - 123",
                "make": "Honda",
                "model": "CB 190R",
                "year": "2024",
                "motorcycle_type": "Urbana",
                "current_mileage": "1250",
            },
        )

        motorcycle = Motorcycle.objects.get(plate_normalized="ABC123")
        self.assertRedirects(response, motorcycle.get_absolute_url())
        self.assertEqual(motorcycle.plate, "ABC - 123")

        listing = self.client.get(
            reverse("customers:motorcycle_list"),
            {"q": "honda"},
        )
        self.assertContains(listing, "ABC - 123")

    def test_duplicate_plate_with_different_format_is_rejected(self):
        Motorcycle.objects.create(
            customer=self.customer,
            plate="abc-123",
            make="Honda",
            model="CB 190R",
        )
        form = MotorcycleForm(
            data={
                "customer": self.customer.pk,
                "plate": "ABC 123",
                "make": "Yamaha",
                "model": "FZ",
                "year": "",
                "motorcycle_type": "",
                "current_mileage": "0",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("plate", form.errors)

    def test_negative_mileage_is_rejected(self):
        form = MotorcycleForm(
            data={
                "customer": self.customer.pk,
                "plate": "XYZ-987",
                "make": "Yamaha",
                "model": "FZ",
                "year": "",
                "motorcycle_type": "",
                "current_mileage": "-1",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("current_mileage", form.errors)


class CustomerPortalTests(TestCase):
    def setUp(self):
        self.reception = StaffUser.objects.create_user(
            username="portal-reception",
            role=StaffUser.Role.RECEPTION,
        )
        self.customer = Customer.objects.create(
            full_name="Cliente Portal",
            phone="999123456",
            dni="12345678",
        )
        self.motorcycle = Motorcycle.objects.create(
            customer=self.customer,
            plate="PORTAL-1",
            make="Honda",
            model="CB",
        )
        self.service = Service.objects.create(
            name="Revisión de frenos",
            description="Revisión",
            default_price="100.00",
            estimated_minutes=30,
        )
        self.order = WorkOrder.objects.create(
            customer=self.customer,
            motorcycle=self.motorcycle,
            created_by=self.reception,
            status=WorkOrder.Status.WAITING_APPROVAL,
            mileage=0,
            complaint="Revisar frenos",
            diagnosis="Cambiar pastillas",
            notes="Nota estrictamente interna",
        )
        WorkOrderLine.objects.create(
            work_order=self.order,
            line_type=WorkOrderLine.LineType.SERVICE,
            service=self.service,
            description_snapshot=self.service.name,
            quantity="1",
            unit_price="100.00",
        )

    def issue_code(self):
        self.client.force_login(self.reception)
        response = self.client.post(
            reverse(
                "customers:customer_portal_code",
                args=[self.customer.pk],
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Código de acceso de un solo uso")
        self.assertIn("no-store", response.headers["Cache-Control"])
        return response.context["portal_code"]

    def test_staff_issued_code_is_hashed_single_use_and_opens_private_portal(self):
        raw_code = self.issue_code()
        stored_code = CustomerPortalCode.objects.get(
            token_digest=customer_portal_code_digest(raw_code)
        )
        self.assertNotIn(raw_code, stored_code.token_digest)

        login = self.client.post(
            reverse("customer_portal:login"),
            {"code": raw_code},
        )
        self.assertRedirects(login, reverse("customer_portal:home"))
        self.assertNotIn("_auth_user_id", self.client.session)
        stored_code.refresh_from_db()
        self.assertIsNotNone(stored_code.used_at)

        portal = self.client.get(reverse("customer_portal:home"))
        self.assertIn("no-store", portal.headers["Cache-Control"])
        self.assertContains(portal, "OT-")
        self.assertContains(portal, "Revisar frenos")
        self.assertContains(portal, "Aprobar presupuesto")
        self.assertNotContains(portal, "12345678")
        self.assertNotContains(portal, "Nota estrictamente interna")
        self.assertEqual(self.client.session.get_expiry_age(), 12 * 60 * 60)

        invalid_reuse = self.client.post(
            reverse("customer_portal:login"),
            {"code": raw_code},
        )
        self.assertContains(invalid_reuse, "no es válido o venció")

    def test_issuing_new_code_invalidates_previous_code(self):
        old_code = self.issue_code()
        new_code = self.issue_code()
        self.assertNotEqual(old_code, new_code)
        self.client.post(
            reverse("customer_portal:login"),
            {"code": old_code},
        )
        self.assertNotIn("customer_portal_customer_id", self.client.session)

        response = self.client.post(
            reverse("customer_portal:login"),
            {"code": new_code},
        )
        self.assertRedirects(response, reverse("customer_portal:home"))

    def test_expired_code_is_rejected(self):
        raw_code = self.issue_code()
        CustomerPortalCode.objects.filter(
            token_digest=customer_portal_code_digest(raw_code)
        ).update(expires_at=timezone.now())

        response = self.client.post(
            reverse("customer_portal:login"),
            {"code": raw_code},
        )

        self.assertContains(response, "no es válido o venció")
        self.assertNotIn("customer_portal_customer_id", self.client.session)

    def test_portal_approval_is_attributed_to_customer_and_audited(self):
        raw_code = self.issue_code()
        self.client.post(
            reverse("customer_portal:login"),
            {"code": raw_code},
        )

        response = self.client.post(
            reverse("customer_portal:order_response", args=[self.order.pk]),
            {"decision": "approve"},
        )

        self.assertRedirects(response, reverse("customer_portal:home"))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, WorkOrder.Status.APPROVED)
        approval = CustomerApproval.objects.get(work_order=self.order)
        self.assertEqual(approval.channel, CustomerApproval.Channel.PORTAL)
        self.assertIsNone(approval.recorded_by)
        event = WorkOrderEvent.objects.get(work_order=self.order)
        self.assertIsNone(event.actor)

    def test_portal_rejection_cancels_order_without_creating_approval(self):
        raw_code = self.issue_code()
        self.client.post(
            reverse("customer_portal:login"),
            {"code": raw_code},
        )

        self.client.post(
            reverse("customer_portal:order_response", args=[self.order.pk]),
            {"decision": "reject"},
        )

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, WorkOrder.Status.CANCELLED)
        self.assertFalse(
            CustomerApproval.objects.filter(work_order=self.order).exists()
        )
        event = WorkOrderEvent.objects.get(work_order=self.order)
        self.assertEqual(
            event.event_type,
            WorkOrderEvent.EventType.CUSTOMER_REJECTED,
        )

    def test_portal_cannot_access_another_customers_order(self):
        raw_code = self.issue_code()
        self.client.post(
            reverse("customer_portal:login"),
            {"code": raw_code},
        )
        other_customer = Customer.objects.create(
            full_name="Otro cliente",
            phone="988123456",
        )
        other_motorcycle = Motorcycle.objects.create(
            customer=other_customer,
            plate="PORTAL-2",
            make="Yamaha",
            model="FZ",
        )
        other_order = WorkOrder.objects.create(
            customer=other_customer,
            motorcycle=other_motorcycle,
            created_by=self.reception,
            status=WorkOrder.Status.WAITING_APPROVAL,
            mileage=0,
            complaint="Orden privada",
        )

        response = self.client.post(
            reverse("customer_portal:order_response", args=[other_order.pk]),
            {"decision": "approve"},
        )

        self.assertEqual(response.status_code, 404)
        other_order.refresh_from_db()
        self.assertEqual(other_order.status, WorkOrder.Status.WAITING_APPROVAL)
        self.assertNotContains(
            self.client.get(reverse("customer_portal:home")),
            "Orden privada",
        )

    def test_staff_without_customer_management_cannot_issue_portal_code(self):
        technician = StaffUser.objects.create_user(
            username="portal-technician",
            role=StaffUser.Role.TECHNICIAN,
        )
        self.client.force_login(technician)

        response = self.client.post(
            reverse(
                "customers:customer_portal_code",
                args=[self.customer.pk],
            )
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(CustomerPortalCode.objects.exists())
