import json
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class TelegramAPIError(Exception):
    pass


def call_telegram(method, payload):
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        raise ImproperlyConfigured("Define TELEGRAM_BOT_TOKEN para conectar el bot.")
    if method not in {"sendMessage", "answerCallbackQuery", "setWebhook"}:
        raise TelegramAPIError("Método de Telegram no permitido.")
    request = Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            data = json.loads(response.read())
    except HTTPError as exc:
        try:
            response_data = json.loads(exc.read())
            description = response_data.get("description", "Error de Telegram.")
        except (ValueError, UnicodeDecodeError):
            description = "Telegram respondió con un error HTTP."
        raise TelegramAPIError(str(description)[:250]) from None
    except (URLError, TimeoutError, OSError, HTTPException) as exc:
        raise TelegramAPIError(
            f"No se pudo conectar con Telegram ({type(exc).__name__})."
        ) from None
    except (ValueError, UnicodeDecodeError) as exc:
        raise TelegramAPIError("Telegram devolvió una respuesta inválida.") from exc
    if not isinstance(data, dict) or not data.get("ok"):
        description = (
            data.get("description", "Telegram rechazó la solicitud.")
            if isinstance(data, dict)
            else "Telegram devolvió una respuesta inválida."
        )
        raise TelegramAPIError(str(description)[:250])
    return data.get("result")
