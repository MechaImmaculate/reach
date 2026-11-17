from django.conf import settings
from django.db import models

from apps.core.models import AppendOnlyModel, TimeStampedModel, UUIDModel


class Purpose(models.TextChoices):
    PLATFORM = "platform"
    SMS = "sms"
    VOICE = "voice"
    REMOTE_CONSULTATION = "remote_consultation"
    LOCATION = "location"
    FACILITY_SHARING = "facility_sharing"
    RESEARCH = "research"
    MODEL_DEVELOPMENT = "model_development"


class ConsentWording(UUIDModel):
    purpose = models.CharField(max_length=25, choices=Purpose)
    version = models.PositiveIntegerField()
    language = models.CharField(max_length=2)
    text = models.TextField()
    approved_reference = models.CharField(max_length=200, blank=True)  # legal / clinical sign-off
    effective_from = models.DateField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["purpose", "version", "language"], name="consentwording_unique_version")
        ]


class ConsentRecord(AppendOnlyModel):
    """Append-only. Current state per (mother, purpose) is the latest row: see the
    `consent_current` view. Withdrawal is a new row with status='withdrawn'."""

    class Status(models.TextChoices):
        GRANTED = "granted"
        DECLINED = "declined"
        WITHDRAWN = "withdrawn"

    class Method(models.TextChoices):
        PAPER = "paper"
        VERBAL_WITNESSED = "verbal_witnessed"
        SMS_REPLY = "sms_reply"
        WEB = "web"
        ASSISTED_CHW = "assisted_chw"
        USSD = "ussd"

    mother = models.ForeignKey("mothers.Mother", on_delete=models.PROTECT, related_name="consents")
    purpose = models.CharField(max_length=25, choices=Purpose)
    status = models.CharField(max_length=10, choices=Status)
    wording = models.ForeignKey(ConsentWording, on_delete=models.PROTECT, related_name="records")
    method = models.CharField(max_length=20, choices=Method)
    captured_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    evidence_ref = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    occurred_at = models.DateTimeField()

    class Meta(AppendOnlyModel.Meta):
        indexes = [models.Index(fields=["mother", "purpose", "-occurred_at"], name="consent_current_lookup_idx")]


class DataSubjectRequest(TimeStampedModel):
    class Kind(models.TextChoices):
        ACCESS = "access"
        CORRECTION = "correction"
        DELETION = "deletion"
        WITHDRAWAL = "withdrawal"
        OBJECTION = "objection"

    class Status(models.TextChoices):
        RECEIVED = "received"
        IN_PROGRESS = "in_progress"
        FULFILLED = "fulfilled"
        REFUSED = "refused"

    mother = models.ForeignKey("mothers.Mother", on_delete=models.PROTECT, related_name="data_requests")
    kind = models.CharField(max_length=12, choices=Kind)
    status = models.CharField(max_length=12, choices=Status, default=Status.RECEIVED)
    requested_at = models.DateTimeField()
    due_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    outcome_note = models.TextField(blank=True)