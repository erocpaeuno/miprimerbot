import hmac
import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt

from messaging.forms import OfferCampaignForm
from messaging.models import OfferCampaign, TelegramAccount, TelegramOutbox
from messaging.services import (
    create_offer_campaign,
    process_telegram_update,
)


@csrf_exempt
@require_POST
def webhook(request):
    secret = settings.TELEGRAM_WEBHOOK_SECRET
    supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not secret or not hmac.compare_digest(supplied, secret):
        return HttpResponse(status=403)
    content_length = request.META.get("CONTENT_LENGTH", "")
    if content_length:
        try:
            if int(content_length) > 65536:
                return HttpResponse(status=413)
        except ValueError:
            return HttpResponse(status=400)
    if len(request.body) > 65536:
        return HttpResponse(status=413)
    try:
        update = json.loads(request.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return HttpResponse(status=400)
    try:
        process_telegram_update(update)
    except ValidationError:
        return HttpResponse(status=400)
    return JsonResponse({"ok": True})


@login_required
def offers(request):
    if not request.user.has_perm("messaging.manage"):
        raise PermissionDenied
    form = OfferCampaignForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        campaign = create_offer_campaign(
            message=form.cleaned_data["message"],
            actor=request.user,
        )
        queued_count = TelegramOutbox.objects.filter(
            event_key__startswith=f"offer:{campaign.pk}:customer:"
        ).count()
        messages.success(
            request,
            f"Oferta registrada y encolada para {queued_count} cliente(s) "
            "con consentimiento. El envío se completará desde la tarea de salida.",
        )
        return redirect("messaging:offers")
    return render(
        request,
        "messaging/offers.html",
        {
            "form": form,
            "campaigns": OfferCampaign.objects.select_related("created_by")[:20],
            "accounts_count": TelegramAccount.objects.filter(
                is_active=True,
                offers_consent=True,
            ).count(),
            "queued_count": TelegramOutbox.objects.filter(
                status=TelegramOutbox.Status.PENDING
            ).count(),
        },
    )
