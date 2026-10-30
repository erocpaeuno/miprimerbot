from django.test import TestCase
from django.urls import reverse
from rest_framework.settings import api_settings

from accounts.models import StaffUser


class StaffAuthenticationTests(TestCase):
    def setUp(self):
        self.user = StaffUser.objects.create_user(
            username="recepcion",
            password="Taller-Password-938!",
            role=StaffUser.Role.RECEPTION,
        )

    def test_profile_requires_login(self):
        response = self.client.get(reverse("accounts:profile"))

        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('accounts:profile')}",
        )

    def test_staff_can_log_in_view_profile_and_log_out(self):
        login = self.client.post(
            reverse("accounts:login"),
            {"username": "recepcion", "password": "Taller-Password-938!"},
        )

        self.assertRedirects(login, reverse("accounts:profile"))
        profile = self.client.get(reverse("accounts:profile"))
        self.assertEqual(profile.status_code, 200)
        self.assertContains(profile, "Recepción")
        self.assertContains(
            profile,
            f'href="{reverse("customers:customer_list")}"',
        )
        self.assertContains(
            profile,
            f'href="{reverse("customers:customer_create")}"',
        )
        self.assertNotContains(profile, "Ofertas por Telegram")

        logout = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(logout, reverse("accounts:login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_superuser_profile_links_to_all_management_modules(self):
        user = StaffUser.objects.create_superuser(
            username="root",
            password="Taller-Password-938!",
        )
        self.client.force_login(user)

        profile = self.client.get(reverse("accounts:profile"))

        self.assertEqual(profile.status_code, 200)
        for route_name in (
            "customers:customer_list",
            "customers:customer_create",
            "customers:motorcycle_list",
            "catalog:service_list",
            "inventory:part_list",
            "workorders:list",
            "maintenance:index",
            "finance:index",
            "messaging:offers",
            "admin:index",
        ):
            with self.subTest(route_name=route_name):
                self.assertContains(
                    profile,
                    f'href="{reverse(route_name)}"',
                )

    def test_invalid_credentials_do_not_authenticate(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "recepcion", "password": "incorrecta"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)


class StaffRolePermissionTests(TestCase):
    def create_staff(self, role):
        return StaffUser.objects.create_user(username=role, role=role)

    def test_reception_can_manage_customers_but_not_finances(self):
        user = self.create_staff(StaffUser.Role.RECEPTION)

        self.assertTrue(user.has_perm("customers.manage_customers"))
        self.assertTrue(user.has_perm("vehicles.manage_vehicles"))
        self.assertFalse(user.has_perm("finance.cash.manage"))
        self.assertFalse(user.has_perm("reports.financial.view"))

    def test_technician_can_update_assigned_work_but_not_cash(self):
        user = self.create_staff(StaffUser.Role.TECHNICIAN)

        self.assertTrue(user.has_perm("workorders.view_assigned"))
        self.assertTrue(user.has_perm("workorders.update_assigned"))
        self.assertFalse(user.has_perm("workorders.view_all"))
        self.assertFalse(user.has_perm("finance.cash.manage"))

    def test_cashier_can_manage_cash_but_not_staff_accounts(self):
        user = self.create_staff(StaffUser.Role.CASHIER)

        self.assertTrue(user.has_perm("finance.cash.manage"))
        self.assertTrue(user.has_perm("reports.financial.view"))
        self.assertFalse(user.has_perm("accounts.manage_staff"))
        self.assertFalse(user.has_perm("workorders.manage"))

    def test_inactive_user_has_no_permissions(self):
        user = self.create_staff(StaffUser.Role.ADMINISTRATOR)
        user.is_active = False

        self.assertFalse(user.has_perm("accounts.manage_staff"))

    def test_superuser_bypasses_role_permissions(self):
        user = StaffUser.objects.create_superuser(
            username="root",
            password="Taller-Password-938!",
        )

        self.assertEqual(user.role, StaffUser.Role.ADMINISTRATOR)
        self.assertTrue(user.has_perm("accounts.manage_staff"))
        self.assertTrue(user.has_perm("finance.cash.manage"))

    def test_api_defaults_to_authenticated_access(self):
        self.assertIn(
            "rest_framework.permissions.IsAuthenticated",
            [permission.__module__ + "." + permission.__name__
             for permission in api_settings.DEFAULT_PERMISSION_CLASSES],
        )
