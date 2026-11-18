from django.apps import AppConfig


def _ip(request):
    # REMOTE_ADDR only: X-Forwarded-For is client-controlled. Revisit when deployed behind a proxy.
    return request.META.get("REMOTE_ADDR") if request is not None else None


def _on_login(sender, request, user, **kwargs):
    from django.utils import timezone

    from apps.audit.models import AuditLog
    AuditLog.objects.create(
        actor=user, action=AuditLog.Action.LOGIN, object_type="auth.user", object_id=str(user.pk),
        ip=_ip(request), user_agent=(request.META.get("HTTP_USER_AGENT", "")[:300] if request else ""),
        occurred_at=timezone.now())


def _on_login_failed(sender, credentials, request=None, **kwargs):
    """Never store the attempted email: store a keyed hash so repeated attempts can be correlated."""
    from django.utils import timezone

    from apps.audit.models import AuditLog
    from apps.core.fields import blind_index
    attempted = (credentials.get("username") or credentials.get("email") or "").strip().lower()
    AuditLog.objects.create(
        action=AuditLog.Action.LOGIN_FAILED, object_type="auth.credentials_hash",
        object_id=blind_index(attempted)[:32] if attempted else "none",
        ip=_ip(request), user_agent=(request.META.get("HTTP_USER_AGENT", "")[:300] if request else ""),
        occurred_at=timezone.now())


class WebConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.web"

    def ready(self):
        from django.contrib.auth.signals import user_logged_in, user_login_failed
        user_logged_in.connect(_on_login, dispatch_uid="reach_audit_login")
        user_login_failed.connect(_on_login_failed, dispatch_uid="reach_audit_login_failed")