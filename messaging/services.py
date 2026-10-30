import hashlib
import secrets
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from customers.models import Customer
from messaging.models import (
    OfferCampaign,
    TelegramAccount,
    TelegramConsentEvent,
    TelegramLinkToken,
    TelegramOrderResponse,
    TelegramOutbox,
    TelegramUpdate,
)
from workorders.models import (
    CustomerApproval,
    WorkOrder,
    WorkOrderEvent,
)


LINK_TOKEN_LIFETIME = timedelta(minutes=15)


@transaction.atomic
def issue_link_token(*, customer_id, actor):
    if not (
        actor.has_perm("customers.manage_customers")
        or actor.has_perm("messaging.manage")
    ):
        raise PermissionDenied("No tienes permiso para vincular clientes.")
    customer = Customer.objects.get(pk=customer_id)
    if TelegramAccount.objects.filter(
        customer=customer,
        is_active=True,
    ).exists():
        raise ValidationError("El cliente ya tiene una cuenta de Telegram activa.")

    now = timezone.now()
    TelegramLinkToken.objects.filter(
        customer=customer,
        used_at__isnull=True,
        expires_at__gt=now,
    ).update(expires_at=now)
    raw_token = secrets.token_urlsafe(24)
    TelegramLinkToken.objects.create(
        customer=customer,
        token_digest=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        issued_by=actor,
        expires_at=now + LINK_TOKEN_LIFETIME,
    )
    return raw_token


def _queue_message(
    *,
    event_key,
    chat_id,
    message_type,
    payload,
    account=None,
    work_order=None,
    method="sendMessage",
):
    message, _created = TelegramOutbox.objects.get_or_create(
        event_key=event_key,
        defaults={
            "account": account,
            "work_order": work_order,
            "chat_id": chat_id,
            "message_type": message_type,
            "method": method,
            "payload": payload,
        },
    )
    return message


@transaction.atomic
def enqueue_order_message(*, work_order_id, message_type):
    work_order = WorkOrder.objects.select_related(
        "customer",
        "motorcycle",
    ).get(pk=work_order_id)
    account = TelegramAccount.objects.filter(
        customer=work_order.customer,
        is_active=True,
        work_updates_consent=True,
    ).first()
    if not account:
        return None

    lines = "\n".join(
        f"- {line.description_snapshot}: {line.quantity} x S/ {line.unit_price}"
        for line in work_order.lines.all()
    )
    if message_type == "approval_request":
        if work_order.status != WorkOrder.Status.WAITING_APPROVAL:
            return None
        text = (
            f"Presupuesto de la orden {work_order.order_number}\n"
            f"Motocicleta: {work_order.motorcycle.plate}\n"
            f"Diagnóstico: {work_order.diagnosis}\n"
            f"{lines}\n"
            f"Total referencial: S/ {work_order.total:.2f}\n"
            "Responde con los botones para aprobar o rechazar."
        )
        reply_markup = {
            "inline_keyboard": [[
                {
                    "text": "Aprobar presupuesto",
                    "callback_data": f"order:{work_order.pk}:yes",
                },
                {
                    "text": "Rechazar",
                    "callback_data": f"order:{work_order.pk}:no",
                },
            ]]
        }
        event_key = f"order:{work_order.pk}:approval-request"
    elif message_type == "work_ready":
        if work_order.status not in {
            WorkOrder.Status.READY,
            WorkOrder.Status.DELIVERED,
        }:
            return None
        text = (
            f"El trabajo de la orden {work_order.order_number} está terminado "
            f"y listo para recojo. Motocicleta: {work_order.motorcycle.plate}."
        )
        reply_markup = None
        event_key = f"order:{work_order.pk}:work-ready"
    else:
        raise ValidationError({"message_type": "Tipo de aviso desconocido."})

    payload = {"chat_id": account.chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _queue_message(
        event_key=event_key,
        account=account,
        work_order=work_order,
        chat_id=account.chat_id,
        message_type=message_type,
        payload=payload,
    )


@transaction.atomic
def create_offer_campaign(*, message, actor):
    if not actor.has_perm("messaging.manage"):
        raise PermissionDenied("No tienes permiso para enviar ofertas.")
    message = message.strip()
    if not message:
        raise ValidationError({"message": "Escribe el contenido de la oferta."})
    campaign = OfferCampaign.objects.create(
        message=message,
        created_by=actor,
    )
    accounts = TelegramAccount.objects.filter(
        is_active=True,
        offers_consent=True,
    ).iterator()
    for account in accounts:
        _queue_message(
            event_key=f"offer:{campaign.pk}:customer:{account.customer_id}",
            account=account,
            chat_id=account.chat_id,
            message_type="offer",
            payload={
                "chat_id": account.chat_id,
                "text": (
                    f"Oferta del taller:\n{message}\n\n"
                    "Para dejar de recibir ofertas, escribe /ofertas off."
                ),
            },
        )
    return campaign


def _queue_account_reply(*, chat_id, text, account=None, event_key):
    return _queue_message(
        event_key=event_key,
        account=account,
        chat_id=chat_id,
        message_type="account_reply" if account else "bot_reply",
        payload={"chat_id": chat_id, "text": text},
    )


def _process_start(*, chat_id, text, update):
    parts = text.split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip():
        _queue_account_reply(
            chat_id=chat_id,
            text=(
                "Para vincular Telegram, solicita en el taller un código "
                "personal de un solo uso. No envíes tu DNI por este chat."
            ),
            event_key=f"update:{update.pk}:start-help",
        )
        return

    token_digest = hashlib.sha256(parts[1].strip().encode("utf-8")).hexdigest()
    token = (
        TelegramLinkToken.objects.select_for_update()
        .select_related("customer")
        .filter(
            token_digest=token_digest,
            used_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .first()
    )
    if not token:
        _queue_account_reply(
            chat_id=chat_id,
            text="El código no es válido o venció. Solicita uno nuevo al taller.",
            event_key=f"update:{update.pk}:start-invalid",
        )
        return
    existing_chat = TelegramAccount.objects.filter(chat_id=chat_id).first()
    if existing_chat and existing_chat.customer_id != token.customer_id:
        _queue_account_reply(
            chat_id=chat_id,
            text="Esta cuenta de Telegram ya está vinculada a otro cliente. Contacta al taller.",
            event_key=f"update:{update.pk}:start-chat-conflict",
        )
        return
    account = TelegramAccount.objects.filter(customer=token.customer).first()
    if account and account.is_active:
        _queue_account_reply(
            chat_id=chat_id,
            text="La cuenta del cliente ya está vinculada. Contacta al taller para actualizarla.",
            event_key=f"update:{update.pk}:start-customer-conflict",
        )
        return

    if account:
        account.chat_id = chat_id
        account.is_active = True
        account.work_updates_consent = False
        account.offers_consent = False
        account.work_updates_consent_at = None
        account.offers_consent_at = None
        account.linked_at = timezone.now()
        account.save()
    else:
        account = TelegramAccount.objects.create(
            customer=token.customer,
            chat_id=chat_id,
        )
    token.used_at = timezone.now()
    token.save(update_fields=["used_at"])
    _queue_account_reply(
        chat_id=chat_id,
        account=account,
        text=(
            f"Cuenta vinculada para {token.customer.full_name}. "
            "No enviaremos avisos ni ofertas sin tu consentimiento. "
            "Escribe /avisos on para recibir novedades de tus trabajos "
            "y /ofertas on para promociones. Usa /baja para desactivar ambos."
        ),
        event_key=f"update:{update.pk}:linked",
    )


def _process_consent_command(*, chat_id, text, update):
    account = TelegramAccount.objects.select_for_update().filter(
        chat_id=chat_id,
        is_active=True,
    ).first()
    if not account:
        _queue_account_reply(
            chat_id=chat_id,
            text="La cuenta no está vinculada. Solicita un código al taller.",
            event_key=f"update:{update.pk}:not-linked",
        )
        return

    command, *args = text.lower().split()
    option = args[0] if args else ""
    now = timezone.now()
    if command == "/baja":
        account.work_updates_consent = False
        account.offers_consent = False
        account.work_updates_consent_at = None
        account.offers_consent_at = None
        account.save()
        TelegramConsentEvent.objects.bulk_create(
            [
                TelegramConsentEvent(
                    account=account,
                    category=TelegramConsentEvent.Category.WORK_UPDATES,
                    granted=False,
                    update=update,
                ),
                TelegramConsentEvent(
                    account=account,
                    category=TelegramConsentEvent.Category.OFFERS,
                    granted=False,
                    update=update,
                ),
            ]
        )
        TelegramOutbox.objects.filter(
            account=account,
            status=TelegramOutbox.Status.PENDING,
            message_type__in={"approval_request", "work_ready", "offer"},
        ).update(status=TelegramOutbox.Status.CANCELLED)
        reply = "Listo. Desactivamos avisos de trabajos y ofertas."
    elif command == "/avisos" and option in {"on", "off"}:
        account.work_updates_consent = option == "on"
        account.work_updates_consent_at = now if option == "on" else None
        account.save(update_fields=[
            "work_updates_consent",
            "work_updates_consent_at",
            "updated_at",
        ])
        TelegramConsentEvent.objects.create(
            account=account,
            category=TelegramConsentEvent.Category.WORK_UPDATES,
            granted=option == "on",
            update=update,
        )
        if option == "off":
            TelegramOutbox.objects.filter(
                account=account,
                status=TelegramOutbox.Status.PENDING,
                message_type__in={"approval_request", "work_ready"},
            ).update(status=TelegramOutbox.Status.CANCELLED)
        reply = (
            "Activamos avisos sobre tus trabajos."
            if option == "on"
            else "Desactivamos avisos sobre tus trabajos."
        )
    elif command == "/ofertas" and option in {"on", "off"}:
        account.offers_consent = option == "on"
        account.offers_consent_at = now if option == "on" else None
        account.save(update_fields=[
            "offers_consent",
            "offers_consent_at",
            "updated_at",
        ])
        TelegramConsentEvent.objects.create(
            account=account,
            category=TelegramConsentEvent.Category.OFFERS,
            granted=option == "on",
            update=update,
        )
        if option == "off":
            TelegramOutbox.objects.filter(
                account=account,
                status=TelegramOutbox.Status.PENDING,
                message_type="offer",
            ).update(status=TelegramOutbox.Status.CANCELLED)
        reply = (
            "Activamos el envío de ofertas."
            if option == "on"
            else "Desactivamos el envío de ofertas."
        )
    elif command == "/desvincular":
        account.is_active = False
        account.work_updates_consent = False
        account.offers_consent = False
        account.work_updates_consent_at = None
        account.offers_consent_at = None
        account.save()
        TelegramConsentEvent.objects.bulk_create(
            [
                TelegramConsentEvent(
                    account=account,
                    category=TelegramConsentEvent.Category.WORK_UPDATES,
                    granted=False,
                    update=update,
                ),
                TelegramConsentEvent(
                    account=account,
                    category=TelegramConsentEvent.Category.OFFERS,
                    granted=False,
                    update=update,
                ),
            ]
        )
        TelegramOutbox.objects.filter(
            account=account,
            status=TelegramOutbox.Status.PENDING,
        ).update(status=TelegramOutbox.Status.CANCELLED)
        reply = "La cuenta fue desvinculada y detuvimos todos los mensajes."
        account = None
    else:
        reply = (
            "Comandos disponibles:\n"
            "/avisos on|off — novedades del trabajo\n"
            "/ofertas on|off — promociones\n"
            "/baja — desactivar todos los mensajes\n"
            "/desvincular — quitar el vínculo"
        )
    _queue_account_reply(
        chat_id=chat_id,
        account=account,
        text=reply,
        event_key=f"update:{update.pk}:command-reply",
    )


def _process_order_callback(*, callback, update):
    query_id = callback.get("id")
    data = callback.get("data", "")
    callback_message = callback.get("message")
    if not isinstance(callback_message, dict):
        return
    chat = callback_message.get("chat", {})
    if not isinstance(chat, dict) or chat.get("type") != "private":
        return
    chat_id = chat.get("id")
    if not isinstance(query_id, str) or not isinstance(chat_id, int):
        return
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "order" or parts[2] not in {"yes", "no"}:
        return
    try:
        work_order_id = int(parts[1])
    except ValueError:
        return

    account = TelegramAccount.objects.select_for_update().filter(
        chat_id=chat_id,
        is_active=True,
        work_updates_consent=True,
    ).first()
    work_order = (
        WorkOrder.objects.select_for_update()
        .select_related("customer")
        .filter(pk=work_order_id)
        .first()
    )
    decision = (
        TelegramOrderResponse.Decision.APPROVED
        if parts[2] == "yes"
        else TelegramOrderResponse.Decision.REJECTED
    )
    response_text = "No se pudo procesar la respuesta."
    if (
        account
        and work_order
        and work_order.customer_id == account.customer_id
        and work_order.status == WorkOrder.Status.WAITING_APPROVAL
        and not TelegramOrderResponse.objects.filter(
            work_order=work_order
        ).exists()
    ):
        TelegramOrderResponse.objects.create(
            work_order=work_order,
            update=update,
            decision=decision,
        )
        old_status = work_order.status
        new_status = (
            WorkOrder.Status.APPROVED
            if decision == TelegramOrderResponse.Decision.APPROVED
            else WorkOrder.Status.CANCELLED
        )
        WorkOrder.objects.filter(pk=work_order.pk).update(
            status=new_status,
            updated_at=timezone.now(),
        )
        if decision == TelegramOrderResponse.Decision.APPROVED:
            CustomerApproval.objects.create(
                work_order=work_order,
                channel=CustomerApproval.Channel.TELEGRAM,
                evidence_note="El cliente aprobó el presupuesto mediante el bot de Telegram.",
                recorded_by=None,
            )
            WorkOrderEvent.objects.create(
                work_order=work_order,
                event_type=WorkOrderEvent.EventType.APPROVAL,
                old_status=old_status,
                new_status=new_status,
                actor=None,
                description="El cliente aprobó el presupuesto mediante Telegram.",
            )
            response_text = "Aprobación registrada. El taller recibió tu respuesta."
        else:
            WorkOrderEvent.objects.create(
                work_order=work_order,
                event_type=WorkOrderEvent.EventType.CUSTOMER_REJECTED,
                old_status=old_status,
                new_status=new_status,
                actor=None,
                description="El cliente rechazó el presupuesto mediante Telegram.",
            )
            response_text = "Rechazo registrado. El taller se pondrá en contacto."

    _queue_message(
        event_key=f"update:{update.pk}:callback-answer",
        chat_id=chat_id,
        message_type="callback_answer",
        method="answerCallbackQuery",
        payload={"callback_query_id": query_id, "text": response_text},
    )


@transaction.atomic
def process_telegram_update(data):
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("update_id"), int)
        or isinstance(data.get("update_id"), bool)
        or data["update_id"] < 0
    ):
        raise ValidationError("La actualización de Telegram no tiene update_id.")
    update_id = data["update_id"]
    update_type = (
        "callback_query"
        if isinstance(data.get("callback_query"), dict)
        else "message"
        if isinstance(data.get("message"), dict)
        else "other"
    )
    update, created = TelegramUpdate.objects.get_or_create(
        update_id=update_id,
        defaults={"update_type": update_type},
    )
    if not created:
        return False

    callback = data.get("callback_query")
    if isinstance(callback, dict):
        _process_order_callback(callback=callback, update=update)
        return True

    message = data.get("message")
    if not isinstance(message, dict):
        return True
    chat = message.get("chat", {})
    if not isinstance(chat, dict) or chat.get("type") != "private":
        return True
    chat_id = chat.get("id")
    text = message.get("text", "")
    if not isinstance(chat_id, int) or not isinstance(text, str):
        return True
    text = text.strip()
    if text.startswith("/start"):
        _process_start(chat_id=chat_id, text=text, update=update)
    elif text and text.split(maxsplit=1)[0].lower() in {
        "/avisos",
        "/ofertas",
        "/baja",
        "/desvincular",
        "/help",
        "/ayuda",
    }:
        _process_consent_command(chat_id=chat_id, text=text, update=update)
    return True


def can_deliver_message(message):
    if not message.account_id:
        return True
    account = message.account
    if not account.is_active or account.chat_id != message.chat_id:
        return False
    if message.message_type == "offer":
        return account.offers_consent
    if message.message_type in {"approval_request", "work_ready"}:
        if not account.work_updates_consent or not message.work_order_id:
            return False
        if message.message_type == "approval_request":
            return (
                message.work_order.status == WorkOrder.Status.WAITING_APPROVAL
                and not TelegramOrderResponse.objects.filter(
                    work_order_id=message.work_order_id
                ).exists()
                and not CustomerApproval.objects.filter(
                    work_order_id=message.work_order_id
                ).exists()
            )
        return message.work_order.status in {
            WorkOrder.Status.READY,
            WorkOrder.Status.DELIVERED,
        }
    return True


def mark_message_failed(*, message, error):
    TelegramOutbox.objects.filter(pk=message.pk).update(
        status=TelegramOutbox.Status.FAILED,
        attempts=F("attempts") + 1,
        last_error=str(error)[:300],
    )


def mark_message_sent(*, message, telegram_message_id=None):
    TelegramOutbox.objects.filter(pk=message.pk).update(
        status=TelegramOutbox.Status.SENT,
        attempts=F("attempts") + 1,
        sent_at=timezone.now(),
        last_error="",
        telegram_message_id=telegram_message_id,
    )


def cancel_message(*, message):
    TelegramOutbox.objects.filter(pk=message.pk).update(
        status=TelegramOutbox.Status.CANCELLED,
    )
