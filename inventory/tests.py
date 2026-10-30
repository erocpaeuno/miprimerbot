from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import StaffUser
from inventory.forms import InventoryMovementForm
from inventory.models import InventoryMovement, Part, Service
from inventory.services import record_movement


class InventoryTests(TestCase):
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
        self.part = Part.objects.create(
            sku="ACEITE-10W40",
            name="Aceite 10W-40",
            unit="litro",
            unit_price=Decimal("35.50"),
            reorder_level=Decimal("2"),
        )

    def add_stock(self, amount="10"):
        return record_movement(
            part_id=self.part.pk,
            movement_type=InventoryMovement.MovementType.ENTRY,
            quantity=Decimal(amount),
            actor=self.admin,
            note="Compra inicial",
            unit_cost=Decimal("20.00"),
        )

    def test_receipt_issue_and_adjustment_update_stock_and_log(self):
        receipt = self.add_stock("10")
        self.assertEqual(receipt.part_id, self.part.pk)
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock, Decimal("10.000"))

        record_movement(
            part_id=self.part.pk,
            movement_type=InventoryMovement.MovementType.EXIT,
            quantity=Decimal("3"),
            actor=self.admin,
            note="Salida de prueba",
        )
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock, Decimal("7.000"))

        record_movement(
            part_id=self.part.pk,
            movement_type=InventoryMovement.MovementType.ADJUSTMENT,
            quantity=Decimal("6.5"),
            actor=self.admin,
            note="Conteo físico",
        )
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock, Decimal("6.500"))
        self.assertEqual(self.part.movements.count(), 3)

    def test_exit_cannot_make_stock_negative_or_leave_partial_movement(self):
        with self.assertRaises(ValidationError):
            record_movement(
                part_id=self.part.pk,
                movement_type=InventoryMovement.MovementType.EXIT,
                quantity=Decimal("1"),
                actor=self.admin,
                note="Salida sin stock",
            )

        self.part.refresh_from_db()
        self.assertEqual(self.part.stock, Decimal("0"))
        self.assertEqual(self.part.movements.count(), 0)

    def test_movements_cannot_be_edited_or_deleted(self):
        movement = self.add_stock()

        with self.assertRaises(ValidationError):
            movement.save()
        with self.assertRaises(ValidationError):
            movement.delete()

    def test_services_are_listed_for_staff_but_only_admin_can_manage(self):
        service = Service.objects.create(
            name="Cambio de aceite",
            default_price=Decimal("45.00"),
            estimated_minutes=30,
        )
        self.client.force_login(self.reception)

        listing = self.client.get(reverse("catalog:service_list"))
        create = self.client.get(reverse("catalog:service_create"))

        self.assertContains(listing, service.name)
        self.assertEqual(create.status_code, 403)

        self.client.force_login(self.admin)
        create = self.client.post(
            reverse("catalog:service_create"),
            {
                "name": "Afinamiento",
                "description": "",
                "default_price": "80.00",
                "estimated_minutes": "60",
                "active": "on",
            },
        )
        self.assertRedirects(create, reverse("catalog:service_list"))
        self.assertTrue(Service.objects.filter(name="Afinamiento").exists())

    def test_inventory_read_and_write_permissions_are_enforced(self):
        response = self.client.get(reverse("inventory:part_list"))
        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('inventory:part_list')}",
        )

        self.client.force_login(self.reception)
        self.assertEqual(
            self.client.get(reverse("inventory:part_list")).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                reverse("inventory:part_create")
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                reverse("inventory:movement_list")
            ).status_code,
            403,
        )

        self.client.force_login(self.technician)
        self.assertEqual(
            self.client.get(reverse("inventory:part_detail", args=[self.part.pk])).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("inventory:movement_create", args=[self.part.pk])).status_code,
            403,
        )

        self.client.force_login(self.cashier)
        self.assertEqual(
            self.client.get(reverse("inventory:part_list")).status_code,
            403,
        )

    def test_admin_can_create_part_and_record_movement_through_web(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("inventory:part_create"),
            {
                "sku": "FILTRO-001",
                "name": "Filtro de aceite",
                "description": "",
                "unit": "unidad",
                "unit_price": "12.50",
                "reorder_level": "2",
                "active": "on",
            },
        )
        part = Part.objects.get(sku="FILTRO-001")
        self.assertRedirects(response, part.get_absolute_url())
        self.assertEqual(part.stock, Decimal("0"))

        response = self.client.post(
            reverse("inventory:movement_create", args=[part.pk]),
            {
                "movement_type": InventoryMovement.MovementType.ENTRY,
                "quantity": "5",
                "unit_cost": "8.00",
                "note": "Compra",
            },
        )
        self.assertRedirects(response, part.get_absolute_url())
        part.refresh_from_db()
        self.assertEqual(part.stock, Decimal("5.000"))

    def test_movement_form_rejects_zero_receipt_but_accepts_zero_count(self):
        receipt = InventoryMovementForm(
            data={
                "movement_type": InventoryMovement.MovementType.ENTRY,
                "quantity": "0",
                "unit_cost": "",
                "note": "Sin cantidad",
            }
        )
        adjustment = InventoryMovementForm(
            data={
                "movement_type": InventoryMovement.MovementType.ADJUSTMENT,
                "quantity": "0",
                "unit_cost": "",
                "note": "Conteo físico sin stock",
            }
        )

        self.assertFalse(receipt.is_valid())
        self.assertTrue(adjustment.is_valid())

    def test_invalid_movements_are_not_saved(self):
        with self.assertRaises(ValidationError):
            record_movement(
                part_id=self.part.pk,
                movement_type=InventoryMovement.MovementType.ENTRY,
                quantity=Decimal("0"),
                actor=self.admin,
                note="Ingreso inválido",
            )
        with self.assertRaises(ValidationError):
            record_movement(
                part_id=self.part.pk,
                movement_type=InventoryMovement.MovementType.ENTRY,
                quantity=Decimal("2"),
                actor=self.admin,
                note=" ",
            )

        self.assertEqual(self.part.movements.count(), 0)
