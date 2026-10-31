import json
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import StaffUser
from customers.models import Customer, Motorcycle
from inventory.models import Service
from messaging.models import (
    OfferCampaign,
    TelegramAccount,
    TelegramConsentEvent,
    TelegramLinkToken,
    TelegramOrderResponse,
    TelegramOutbox,
    TelegramUpdate,
)
from messaging.services import (
    create_offer_campaign,
    enqueue_order_message,
    issue_link_token,
    process_telegram_update,
)
from workorders.models import (
    CustomerApproval,
    WorkOrder,
    WorkOrderEvent,
    WorkOrderLine,
)
from workorders.services import (
    add_work_order_line,
    create_work_order,
    transition_work_order,
)


class TelegramIntegrationTests(TestCase):
    def setUp(self):
        self.admin = StaffUser.objects.create_user(
            username="admin",
            role=StaffUser.Role.ADMINISTRATOR,
        )
        self.reception = StaffUser.objects.create_user(
            username="recepcion",
            role=StaffUser.Role.RECEPTION,
        )
        self.cashier = StaffUser.objects.create_user(
            username="caja",
            role=StaffUser.Role.CASHIER,
        )
        self.technician = StaffUser.objects.create_user(
            username="tecnico",
            role=StaffUser.Role.TECHNICIAN,
        )
        self.customer = Customer.objects.create(
            full_name="María Quispe",
            phone="999123456",
            dni="12345678",
        )
        self.motorcycle = Motorcycle.objects.create(
            customer=self.customer,
            plate="ABC-123",
            make="Honda",
            model="CB 190R",
        )
        self.service = Service.objects.create(
            name="Cambio de aceite",
            default_price=Decimal("45.00"),
        )

    def make_order_waiting_approval(self):
        order = create_work_order(
            data={
                "customer": self.customer,
                "motorcycle": self.motorcycle,
                "assigned_to": self.technician,
                "mileage": 0,
                "complaint": "Revisión general.",
                "diagnosis": "Servicio necesario.",
                "notes": "",
            },
            actor=self.reception,
        )
        transition_work_order(
            work_order_id=order.pk,
            new_status=WorkOrder.Status.RECEIVED,
            actor=self.reception,
        )
        transition_work_order(
            work_order_id=order.pk,
            new_status=WorkOrder.Status.DIAGNOSING,
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
        return order

    def telegram_update(self, update_id, *, chat_id=90001, text=None, callback=None):
        if callback is not None:
            data = {
                "update_id": update_id,
                "callback_query": callback,
            }
        else:
            data = {
                "update_id": update_id,
                "message": {
                    "chat": {"id": chat_id, "type": "private"},
                    "text": text or "",
                },
            }
        return process_telegram_update(data)

    def make_account(
        self,
        *,
        customer=None,
        chat_id=90001,
        work_updates=False,
        offers=False,
    ):
        return TelegramAccount.objects.create(
            customer=customer or self.customer,
            chat_id=chat_id,
            work_updates_consent=work_updates,
            offers_consent=offers,
            work_updates_consent_at=timezone.now() if work_updates else None,
            offers_consent_at=timezone.now() if offers else None,
        )

    def test_staff_issues_one_time_token_and_start_links_without_consent(self):
        token = issue_link_token(
            customer_id=self.customer.pk,
            actor=self.reception,
        )
        record = TelegramLinkToken.objects.get(customer=self.customer)
        self.assertNotEqual(record.token_digest, token)
        self.assertEqual(len(record.token_digest), 64)

        self.telegram_update(100, text=f"/start {token}")
        account = TelegramAccount.objects.get(customer=self.customer)
        record.refresh_from_db()
        self.assertEqual(account.chat_id, 90001)
        self.assertTrue(account.is_active)
        self.assertFalse(account.work_updates_consent)
        self.assertFalse(account.offers_consent)
        self.assertIsNotNone(record.used_at)
        self.assertTrue(
            TelegramOutbox.objects.filter(
                event_key="update:1:linked",
                message_type="account_reply",
            ).exists()
        )

        self.telegram_update(101, text=f"/start {token}")
        self.assertEqual(TelegramAccount.objects.count(), 1)
        self.assertEqual(TelegramUpdate.objects.count(), 2)

    def test_dni_is_not_used_for_linking_and_expired_code_is_rejected(self):
        self.telegram_update(200, text="/start 12345678")
        self.assertFalse(TelegramAccount.objects.exists())
        self.assertTrue(
            TelegramOutbox.objects.filter(
                event_key="update:1:start-invalid"
            ).exists()
        )

        token = issue_link_token(customer_id=self.customer.pk, actor=self.admin)
        TelegramLinkToken.objects.update(expires_at=timezone.now())
        self.telegram_update(201, text=f"/start {token}")
        self.assertFalse(TelegramAccount.objects.exists())

    def test_reception_can_issue_code_but_cashier_cannot(self):
        with self.assertRaises(PermissionDenied):
            issue_link_token(customer_id=self.customer.pk, actor=self.cashier)

        self.client.force_login(self.reception)
        response = self.client.post(
            reverse(
                "customers:customer_telegram_link",
                args=[self.customer.pk],
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Código de un solo uso")
        self.client.force_login(self.cashier)
        denied = self.client.post(
            reverse(
                "customers:customer_telegram_link",
                args=[self.customer.pk],
            )
        )
        self.assertEqual(denied.status_code, 403)

    def test_opt_in_and_opt_out_are_explicit_and_audited(self):
        account = self.make_account()
        self.telegram_update(300, text="/avisos on")
        self.telegram_update(301, text="/ofertas on")
        account.refresh_from_db()
        self.assertTrue(account.work_updates_consent)
        self.assertTrue(account.offers_consent)
        self.assertEqual(
            TelegramConsentEvent.objects.filter(account=account, granted=True).count(),
            2,
        )

        self.telegram_update(302, text="/baja")
        account.refresh_from_db()
        self.assertFalse(account.work_updates_consent)
        self.assertFalse(account.offers_consent)
        self.assertEqual(
            TelegramConsentEvent.objects.filter(account=account, granted=False).count(),
            2,
        )

    def test_unlinked_user_cannot_grant_consent(self):
        self.telegram_update(350, text="/ofertas on")
        self.assertFalse(TelegramAccount.objects.exists())
        self.assertFalse(TelegramConsentEvent.objects.exists())

    def test_budget_message_is_queued_only_when_work_updates_are_consented(self):
        order = self.make_order_waiting_approval()
        self.assertFalse(
            TelegramOutbox.objects.filter(
                event_key=f"order:{order.pk}:approval-request"
            ).exists()
        )

        self.make_account(work_updates=True)
        enqueue_order_message(
            work_order_id=order.pk,
            message_type="approval_request",
        )
        message = TelegramOutbox.objects.get(
            event_key=f"order:{order.pk}:approval-request"
        )
        self.assertIn("S/ 45.00", message.payload["text"])
        self.assertEqual(
            message.payload["reply_markup"]["inline_keyboard"][0][0]["callback_data"],
            f"order:{order.pk}:yes",
        )

    def test_budget_message_is_not_delivered_after_manual_approval(self):
        from messaging.services import can_deliver_message
        from workorders.services import approve_work_order

        self.make_account(work_updates=True)
        order = self.make_order_waiting_approval()
        outgoing = TelegramOutbox.objects.get(
            event_key=f"order:{order.pk}:approval-request"
        )
        approve_work_order(
            work_order_id=order.pk,
            channel=CustomerApproval.Channel.PHONE,
            evidence_note="Confirmado por llamada.",
            actor=self.reception,
        )
        outgoing.refresh_from_db()
        self.assertFalse(can_deliver_message(outgoing))

    def test_work_ready_notification_is_queued_after_transition(self):
        account = self.make_account(work_updates=True)
        order = self.make_order_waiting_approval()
        from messaging.services import process_telegram_update

        process_telegram_update(
            {
                "update_id": 450,
                "callback_query": {
                    "id": "approve-ready-flow",
                    "data": f"order:{order.pk}:yes",
                    "message": {
                        "chat": {
                            "id": account.chat_id,
                            "type": "private",
                        }
                    },
                },
            }
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
        outgoing = TelegramOutbox.objects.get(
            event_key=f"order:{order.pk}:work-ready"
        )
        self.assertIn("listo para recojo", outgoing.payload["text"])

    def test_telegram_approval_is_bound_to_customer_and_audited(self):
        account = self.make_account(work_updates=True)
        order = self.make_order_waiting_approval()
        callback = {
            "id": "callback-1",
            "data": f"order:{order.pk}:yes",
            "message": {"chat": {"id": account.chat_id, "type": "private"}},
        }
        self.telegram_update(400, callback=callback)
        order.refresh_from_db()
        self.assertEqual(order.status, WorkOrder.Status.APPROVED)
        approval = CustomerApproval.objects.get(work_order=order)
        self.assertEqual(approval.channel, CustomerApproval.Channel.TELEGRAM)
        self.assertIsNone(approval.recorded_by)
        event = order.events.get(event_type=WorkOrderEvent.EventType.APPROVAL)
        self.assertIsNone(event.actor)
        self.assertTrue(
            TelegramOrderResponse.objects.filter(
                work_order=order,
                decision=TelegramOrderResponse.Decision.APPROVED,
            ).exists()
        )

        self.telegram_update(400, callback=callback)
        self.assertEqual(TelegramOrderResponse.objects.filter(work_order=order).count(), 1)

    def test_telegram_rejection_cancels_order_and_other_customer_cannot_respond(self):
        order = self.make_order_waiting_approval()
        other_customer = Customer.objects.create(
            full_name="Otro cliente",
            phone="988123456",
        )
        account = self.make_account(
            customer=other_customer,
            chat_id=90002,
            work_updates=True,
        )
        callback = {
            "id": "callback-other",
            "data": f"order:{order.pk}:no",
            "message": {"chat": {"id": account.chat_id, "type": "private"}},
        }
        self.telegram_update(500, callback=callback)
        order.refresh_from_db()
        self.assertEqual(order.status, WorkOrder.Status.WAITING_APPROVAL)
        self.assertFalse(TelegramOrderResponse.objects.filter(work_order=order).exists())

        account.customer = self.customer
        account.save()
        callback["id"] = "callback-reject"
        callback["message"]["chat"]["id"] = account.chat_id
        self.telegram_update(501, callback=callback)
        order.refresh_from_db()
        self.assertEqual(order.status, WorkOrder.Status.CANCELLED)
        event = order.events.get(
            event_type=WorkOrderEvent.EventType.CUSTOMER_REJECTED
        )
        self.assertIsNone(event.actor)

    def test_offer_campaign_targets_only_active_opted_in_accounts(self):
        opted_in = self.make_account(offers=True)
        opted_out_customer = Customer.objects.create(
            full_name="Cliente sin oferta",
            phone="987654321",
        )
        self.make_account(
            customer=opted_out_customer,
            chat_id=90002,
            offers=False,
        )
        campaign = create_offer_campaign(
            message="Cambio de aceite con descuento",
            actor=self.admin,
        )
        messages = TelegramOutbox.objects.filter(message_type="offer")
        self.assertEqual(messages.count(), 1)
        self.assertEqual(messages.get().account, opted_in)
        self.assertTrue(OfferCampaign.objects.filter(pk=campaign.pk).exists())
        with self.assertRaises(PermissionDenied):
            create_offer_campaign(message="Oferta", actor=self.reception)

    def test_only_administrator_can_use_offer_campaign_page(self):
        self.client.force_login(self.cashier)
        self.assertEqual(
            self.client.get(reverse("messaging:offers")).status_code,
            403,
        )
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get(reverse("messaging:offers")).status_code,
            200,
        )

    def test_revoked_consent_blocks_queued_offer_delivery(self):
        from messaging.services import can_deliver_message

        account = self.make_account(offers=True)
        create_offer_campaign(message="Oferta", actor=self.admin)
        outgoing = TelegramOutbox.objects.get(message_type="offer")
        self.assertTrue(can_deliver_message(outgoing))
        account.offers_consent = False
        account.offers_consent_at = None
        account.save(update_fields=["offers_consent", "offers_consent_at"])
        outgoing.refresh_from_db()
        self.assertFalse(can_deliver_message(outgoing))

    def test_offer_opt_out_cancels_pending_campaign_messages(self):
        account = self.make_account(offers=True)
        create_offer_campaign(message="Oferta", actor=self.admin)
        outgoing = TelegramOutbox.objects.get(message_type="offer")
        self.telegram_update(800, text="/ofertas off")
        outgoing.refresh_from_db()
        self.assertEqual(outgoing.status, TelegramOutbox.Status.CANCELLED)
        account.refresh_from_db()
        self.assertFalse(account.offers_consent)

    @override_settings(TELEGRAM_WEBHOOK_SECRET="webhook-secret")
    def test_webhook_rejects_bad_secret_and_deduplicates_valid_updates(self):
        url = reverse("messaging:webhook")
        body = json.dumps(
            {
                "update_id": 900,
                "message": {
                    "chat": {"id": 9, "type": "private"},
                    "text": "/help",
                },
            }
        )
        denied = self.client.post(
            url,
            data=body,
            content_type="application/json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="wrong-secret",
        )
        self.assertEqual(denied.status_code, 403)
        self.assertFalse(TelegramUpdate.objects.exists())

        headers = {"HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN": "webhook-secret"}
        first = self.client.post(
            url,
            data=body,
            content_type="application/json",
            **headers,
        )
        duplicate = self.client.post(
            url,
            data=body,
            content_type="application/json",
            **headers,
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(TelegramUpdate.objects.count(), 1)
        self.assertEqual(TelegramOutbox.objects.count(), 1)

    @override_settings(TELEGRAM_WEBHOOK_SECRET="webhook-secret")
    def test_webhook_rejects_oversized_and_invalid_json(self):
        url = reverse("messaging:webhook")
        headers = {"HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN": "webhook-secret"}
        invalid = self.client.post(
            url,
            data="{",
            content_type="application/json",
            **headers,
        )
        self.assertEqual(invalid.status_code, 400)
        oversized = self.client.post(
            url,
            data=" " * 65537,
            content_type="application/json",
            **headers,
        )
        self.assertEqual(oversized.status_code, 413)

    def test_group_messages_cannot_link_customer_account(self):
        token = issue_link_token(
            customer_id=self.customer.pk,
            actor=self.reception,
        )
        process_telegram_update(
            {
                "update_id": 1100,
                "message": {
                    "chat": {"id": -90001, "type": "group"},
                    "text": f"/start {token}",
                },
            }
        )
        self.assertFalse(TelegramAccount.objects.exists())

    @override_settings(TELEGRAM_BOT_TOKEN="test-token")
    def test_outbox_command_sends_pending_message_and_tracks_result(self):
        from django.core.management import call_command

        outgoing = TelegramOutbox.objects.create(
            event_key="test:send",
            chat_id=90001,
            message_type="bot_reply",
            payload={"chat_id": 90001, "text": "Hola"},
        )
        with patch(
            "messaging.management.commands.send_telegram_outbox.call_telegram",
            return_value={"message_id": 123},
        ) as send:
            call_command("send_telegram_outbox")
        outgoing.refresh_from_db()
        self.assertEqual(outgoing.status, TelegramOutbox.Status.SENT)
        self.assertEqual(outgoing.telegram_message_id, 123)
        self.assertEqual(outgoing.attempts, 1)
        send.assert_called_once_with("sendMessage", outgoing.payload)

    @override_settings(TELEGRAM_BOT_TOKEN="test-token")
    def test_outbox_failure_is_persisted_without_exposing_token(self):
        from django.core.management import call_command
        from messaging.telegram_api import TelegramAPIError

        outgoing = TelegramOutbox.objects.create(
            event_key="test:failed",
            chat_id=90001,
            message_type="bot_reply",
            payload={"chat_id": 90001, "text": "Hola"},
        )
        with patch(
            "messaging.management.commands.send_telegram_outbox.call_telegram",
            side_effect=TelegramAPIError("chat not found"),
        ):
            call_command("send_telegram_outbox")
        outgoing.refresh_from_db()
        self.assertEqual(outgoing.status, TelegramOutbox.Status.FAILED)
        self.assertEqual(outgoing.last_error, "chat not found")
        self.assertNotIn("test-token", outgoing.last_error)

    @override_settings(TELEGRAM_BOT_TOKEN="test-token")
    def test_outbox_watch_repeats_until_interrupted(self):
        from messaging.management.commands.send_telegram_outbox import (
            Command as OutboxCommand,
        )

        command = OutboxCommand()
        with (
            patch.object(command, "_send_pending", return_value=(0, 0, 0)) as send,
            patch(
                "messaging.management.commands.send_telegram_outbox.sleep",
                side_effect=[None, KeyboardInterrupt],
            ),
        ):
            with self.assertRaises(KeyboardInterrupt):
                command.handle(
                    limit=100,
                    retry_failed=True,
                    watch=True,
                    interval=10,
                )

        self.assertEqual(send.call_count, 2)
        self.assertEqual(send.call_args_list[0].args, (100, True))
        self.assertEqual(send.call_args_list[1].args, (100, True))

    def test_failed_outbox_message_can_be_requeued_explicitly(self):
        from django.core.management import call_command

        outgoing = TelegramOutbox.objects.create(
            event_key="test:requeue",
            chat_id=90001,
            message_type="bot_reply",
            status=TelegramOutbox.Status.FAILED,
            attempts=5,
            last_error="temporary failure",
            payload={"chat_id": 90001, "text": "Hola"},
        )
        call_command(
            "requeue_telegram_message",
            "--message-id",
            str(outgoing.pk),
        )
        outgoing.refresh_from_db()
        self.assertEqual(outgoing.status, TelegramOutbox.Status.PENDING)
        self.assertEqual(outgoing.attempts, 0)
        self.assertEqual(outgoing.last_error, "")

    @override_settings(
        TELEGRAM_BOT_TOKEN="test-token",
        TELEGRAM_WEBHOOK_SECRET="webhook-secret",
    )
    def test_webhook_registration_command_requires_https_and_registers_secret(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command(
                "set_telegram_webhook",
                "--url",
                "http://example.test/telegram/webhook/",
            )
        with patch(
            "messaging.management.commands.set_telegram_webhook.call_telegram",
            return_value=True,
        ) as call_api:
            call_command(
                "set_telegram_webhook",
                "--url",
                "https://example.test/telegram/webhook/",
            )
        call_api.assert_called_once_with(
            "setWebhook",
            {
                "url": "https://example.test/telegram/webhook/",
                "secret_token": "webhook-secret",
                "allowed_updates": ["message", "callback_query"],
            },
        )
