from django.http import JsonResponse


def health(request):
    return JsonResponse({"service": "taller-motos", "status": "ok"})
