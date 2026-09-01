import hmac
import logging

from django.conf import settings
from django.http import HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from integrations.checker import run_checks

logger = logging.getLogger(__name__)


def _authorized(request) -> bool:
    provided = request.headers.get("X-Cron-Secret") or request.POST.get("token") or ""
    expected = settings.CRON_SECRET or ""
    return hmac.compare_digest(str(provided), str(expected))


@csrf_exempt
@require_POST
def run_checks_webhook(request):
    if not _authorized(request):
        return HttpResponseForbidden("invalid cron secret")
    result = run_checks()
    logger.info("Webhook run_checks complete: %s", result)
    return JsonResponse({"ok": True, **result})
