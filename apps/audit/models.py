from django.conf import settings
from django.db import models

from apps.core.models import AppendOnlyModel, TimeStampedModel


class AuditLog(AppendOnlyModel):
    """Material changes and sensitive actions. `changes` holds redacted field diffs (never PII values)."""

    class Action(models.TextChoices):
        CREATE = "create"
        UPDATE = "update"
        DELETE = "delete"
        LOGIN = "login"
        LOGIN_FAILED = "login_failed"
        OVERRIDE = "override"
        CONSENT_CHANGE = "consent_change"
        EXPORT = "export"
        ACCESS_GRANT = "access_grant"
        ACCESS_REVOKE = "access_revoke"

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    facility = models.ForeignKey("facilities.Facility", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    mother = models.ForeignKey("mothers.Mother", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    action = models.CharField(max_length=16, choices=Action)
    object_type = models.CharField(max_length=80)
    object_id = models.CharField(max_length=64)
    changes = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    request_id = models.UUIDField(null=True, blank=True)
    occurred_at = models.DateTimeField()

    class Meta(AppendOnlyModel.Meta):
        indexes = [
            models.Index(fields=["object_type", "object_id", "-occurred_at"], name="audit_object_idx"),
            models.Index(fields=["actor", "-occurred_at"], name="audit_actor_idx"),
            models.Index(fields=["mother", "-occurred_at"], name="audit_mother_idx"),
        ]


class AccessLog(AppendOnlyModel):
    """Who looked at whose record, and why. High volume: first partitioning candidate (D-19)."""

    class Purpose(models.TextChoices):
        CARE = "care"
        REFERRAL = "referral"
        FOLLOW_UP = "follow_up"
        ADMINISTRATION = "administration"
        BREAK_GLASS = "break_glass"  # emergency access outside normal scope; reviewed afterwards

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    mother = models.ForeignKey("mothers.Mother", on_delete=models.PROTECT, related_name="+")
    facility = models.ForeignKey("facilities.Facility", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    resource = models.CharField(max_length=80)
    purpose = models.CharField(max_length=16, choices=Purpose)
    occurred_at = models.DateTimeField()

    class Meta(AppendOnlyModel.Meta):
        indexes = [
            models.Index(fields=["mother", "-occurred_at"], name="accesslog_mother_idx"),
            models.Index(fields=["actor", "-occurred_at"], name="accesslog_actor_idx"),
        ]


class DataExport(AppendOnlyModel):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=60)
    scope = models.JSONField(default=dict)
    purpose = models.CharField(max_length=200)
    row_count = models.PositiveIntegerField()
    small_cell_suppressed = models.BooleanField(default=False)
    includes_synthetic = models.BooleanField(default=False)
    occurred_at = models.DateTimeField()


class SecurityIncident(TimeStampedModel):
    class Severity(models.TextChoices):
        LOW = "low"
        MEDIUM = "medium"
        HIGH = "high"
        CRITICAL = "critical"

    class Status(models.TextChoices):
        DETECTED = "detected"
        CONTAINED = "contained"
        CLOSED = "closed"

    severity = models.CharField(max_length=8, choices=Severity)
    status = models.CharField(max_length=10, choices=Status, default=Status.DETECTED)
    description = models.TextField()
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    detected_at = models.DateTimeField()
    contained_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    notified_odpc_at = models.DateTimeField(null=True, blank=True)  # regulator notification, if required
    notes = models.TextField(blank=True)
