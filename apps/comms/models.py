import pgtrigger
from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Now

from apps.core.fields import EncryptedTextField
from apps.core.models import AppendOnlyModel, TimeStampedModel, UUIDModel


class Conversation(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open"
        CLOSED = "closed"

    mother = models.ForeignKey("mothers.Mother", on_delete=models.PROTECT, related_name="conversations")
    episode = models.ForeignKey("care.PregnancyEpisode", null=True, blank=True, on_delete=models.PROTECT, related_name="conversations")
    facility = models.ForeignKey("facilities.Facility", on_delete=models.PROTECT, related_name="conversations")
    status = models.CharField(max_length=8, choices=Status, default=Status.OPEN)
    opened_at = models.DateTimeField()
    last_message_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["mother", "facility"],
                condition=Q(status="open"),
                name="conversation_one_open_per_mother_facility",
            ),
        ]


class NotificationTemplate(TimeStampedModel):
    """Outbound wording. Anything a mother might act on needs clinical approval before use."""

    code = models.CharField(max_length=60)
    channel = models.CharField(max_length=10)
    language = models.CharField(max_length=2)
    version = models.PositiveIntegerField(default=1)
    body = models.TextField()
    clinically_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["code", "channel", "language", "version"], name="notificationtemplate_unique"),
            models.CheckConstraint(
                condition=Q(clinically_approved=False) | Q(approved_at__isnull=False),
                name="notificationtemplate_approval_dated",
            ),
        ]


class Message(UUIDModel):
    """One message in either direction. `latest_status` is denormalised from MessageDeliveryEvent
    (updated in the same transaction; advances by rank, never by arrival order)."""

    class Direction(models.TextChoices):
        IN = "in"
        OUT = "out"

    class Channel(models.TextChoices):
        SMS = "sms"
        USSD = "ussd"
        WEB = "web"
        CHW = "chw"

    class SenderKind(models.TextChoices):
        MOTHER = "mother"
        CHW = "chw"
        PROVIDER = "provider"
        SYSTEM = "system"

    class Purpose(models.TextChoices):
        CONCERN = "concern"
        REMINDER = "reminder"
        REFERRAL_INSTRUCTION = "referral_instruction"
        CONSULT_INVITE = "consult_invite"
        SAFETY_INSTRUCTION = "safety_instruction"
        GENERAL = "general"

    class Status(models.TextChoices):
        CREATED = "created"
        QUEUED = "queued"
        SUBMITTED = "submitted"
        SENT = "sent"
        DELIVERED = "delivered"
        FAILED = "failed"
        RECEIVED = "received"  # inbound

    # Rank used to advance latest_status safely when webhooks arrive out of order.
    STATUS_RANK = {"created": 0, "queued": 1, "submitted": 2, "sent": 3, "delivered": 5, "failed": 4, "received": 4}

    conversation = models.ForeignKey(Conversation, on_delete=models.PROTECT, related_name="messages")
    direction = models.CharField(max_length=3, choices=Direction)
    channel = models.CharField(max_length=5, choices=Channel)
    sender_kind = models.CharField(max_length=10, choices=SenderKind)
    sender_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    purpose = models.CharField(max_length=24, choices=Purpose, default=Purpose.GENERAL)
    body = EncryptedTextField()
    language = models.CharField(max_length=2, blank=True)
    template = models.ForeignKey(NotificationTemplate, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    in_reply_to = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="replies")
    provider = models.CharField(max_length=40, blank=True)
    provider_message_id = models.CharField(max_length=120, blank=True)
    idempotency_key = models.CharField(max_length=120, null=True, blank=True)  # offline / client resubmission
    segments = models.PositiveSmallIntegerField(null=True, blank=True)
    provider_cost = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    latest_status = models.CharField(max_length=10, choices=Status, default=Status.CREATED)
    latest_status_at = models.DateTimeField(null=True, blank=True)
    occurred_at = models.DateTimeField()  # provider / device time
    recorded_at = models.DateTimeField(db_default=Now(), editable=False)  # server time, set by the DB

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_message_id"],
                condition=~Q(provider_message_id=""),
                name="message_unique_provider_message_id",
            ),
            models.UniqueConstraint(
                fields=["idempotency_key"],
                condition=Q(idempotency_key__isnull=False),
                name="message_unique_idempotency_key",
            ),
        ]
        indexes = [
            models.Index(fields=["conversation", "-occurred_at"], name="message_conversation_time_idx"),
            models.Index(
                fields=["latest_status", "recorded_at"],
                condition=Q(latest_status__in=["created", "queued", "submitted", "failed"]),
                name="message_unsettled_idx",
            ),
        ]


class WebhookEvent(UUIDModel):
    """Raw provider callback, stored BEFORE processing. Payload is immutable; processing
    columns are mutable. Replay-safe via the unique (provider, provider_event_id)."""

    class Processing(models.TextChoices):
        PENDING = "pending"
        PROCESSED = "processed"
        FAILED = "failed"
        REJECTED = "rejected"  # bad signature

    provider = models.CharField(max_length=40)
    provider_event_id = models.CharField(max_length=160)
    event_type = models.CharField(max_length=60)
    payload = models.JSONField()
    signature_valid = models.BooleanField(default=False)
    received_at = models.DateTimeField(auto_now_add=True)
    processing_status = models.CharField(max_length=10, choices=Processing, default=Processing.PENDING)
    processed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["provider", "provider_event_id"], name="webhookevent_unique_event")
        ]
        indexes = [models.Index(fields=["processing_status", "received_at"], name="webhook_pending_idx")]
        triggers = [
            pgtrigger.ReadOnly(
                name="immutable_payload",
                fields=["provider", "provider_event_id", "event_type", "payload", "received_at"],
            ),
            pgtrigger.Protect(name="no_delete", operation=pgtrigger.Delete),
        ]


class MessageDeliveryEvent(AppendOnlyModel):
    message = models.ForeignKey(Message, on_delete=models.PROTECT, related_name="events")
    status = models.CharField(max_length=10, choices=Message.Status)
    provider_status_raw = models.CharField(max_length=80, blank=True)
    error_code = models.CharField(max_length=60, blank=True)
    webhook_event = models.ForeignKey(WebhookEvent, null=True, blank=True, on_delete=models.PROTECT, related_name="delivery_events")
    occurred_at = models.DateTimeField()

    class Meta(AppendOnlyModel.Meta):
        indexes = [models.Index(fields=["message", "occurred_at"], name="msgdelivery_message_time_idx")]


class CallSession(TimeStampedModel):
    """An ordinary telephone call via the telephony provider (the only channel basic-phone mothers need)."""

    class Direction(models.TextChoices):
        OUTBOUND = "outbound"
        INBOUND = "inbound"

    class Purpose(models.TextChoices):
        CALLBACK = "callback"
        CONSULT_FALLBACK = "consult_fallback"
        FOLLOW_UP = "follow_up"

    class Status(models.TextChoices):
        REQUESTED = "requested"
        RINGING = "ringing"
        ANSWERED = "answered"
        COMPLETED = "completed"
        NO_ANSWER = "no_answer"
        BUSY = "busy"
        FAILED = "failed"

    mother = models.ForeignKey("mothers.Mother", on_delete=models.PROTECT, related_name="call_sessions")
    provider_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    facility = models.ForeignKey("facilities.Facility", on_delete=models.PROTECT, related_name="+")
    direction = models.CharField(max_length=8, choices=Direction, default=Direction.OUTBOUND)
    purpose = models.CharField(max_length=20, choices=Purpose)
    provider = models.CharField(max_length=40, blank=True)
    provider_call_id = models.CharField(max_length=120, blank=True)
    latest_status = models.CharField(max_length=10, choices=Status, default=Status.REQUESTED)
    requested_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_s = models.PositiveIntegerField(null=True, blank=True)
    provider_cost = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    failure_reason = models.CharField(max_length=120, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_call_id"],
                condition=~Q(provider_call_id=""),
                name="callsession_unique_provider_call_id",
            ),
            models.CheckConstraint(
                condition=Q(ended_at__isnull=True) | Q(started_at__isnull=True) | Q(ended_at__gte=F("started_at")),
                name="callsession_end_after_start",
            ),
        ]


class CallSessionEvent(AppendOnlyModel):
    call_session = models.ForeignKey(CallSession, on_delete=models.PROTECT, related_name="events")
    status = models.CharField(max_length=10, choices=CallSession.Status)
    webhook_event = models.ForeignKey(WebhookEvent, null=True, blank=True, on_delete=models.PROTECT, related_name="call_events")
    detail = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField()

    class Meta(AppendOnlyModel.Meta):
        indexes = [models.Index(fields=["call_session", "occurred_at"], name="callevent_session_time_idx")]


class Consultation(TimeStampedModel):
    class Mode(models.TextChoices):
        AUDIO = "audio"
        VIDEO = "video"
        PHONE = "phone"

    class Status(models.TextChoices):
        SCHEDULED = "scheduled"
        INITIATED = "initiated"
        WAITING = "waiting"
        IN_PROGRESS = "in_progress"
        COMPLETED = "completed"
        CANCELLED = "cancelled"
        FAILED = "failed"

    mother = models.ForeignKey("mothers.Mother", on_delete=models.PROTECT, related_name="consultations")
    episode = models.ForeignKey("care.PregnancyEpisode", null=True, blank=True, on_delete=models.PROTECT, related_name="consultations")
    provider = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    facility = models.ForeignKey("facilities.Facility", on_delete=models.PROTECT, related_name="consultations")
    mode = models.CharField(max_length=6, choices=Mode)
    status = models.CharField(max_length=12, choices=Status, default=Status.SCHEDULED)
    reason = models.TextField(blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    outcome = models.TextField(blank=True)
    follow_up_instructions = models.TextField(blank=True)
    consent_record = models.ForeignKey("consent.ConsentRecord", null=True, blank=True, on_delete=models.PROTECT, related_name="consultations")
    room_ref = models.CharField(max_length=80, blank=True)  # unguessable; never reused
    room_expires_at = models.DateTimeField(null=True, blank=True)
    recording_enabled = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(recording_enabled=False), name="consultation_recording_disabled"),
            models.CheckConstraint(
                condition=Q(started_at__isnull=True) | Q(consent_record__isnull=False),
                name="consultation_consent_required_to_start",
            ),
            models.CheckConstraint(
                condition=~Q(status="completed") | ~Q(outcome=""),
                name="consultation_outcome_required_to_complete",
            ),
            models.CheckConstraint(
                condition=Q(ended_at__isnull=True) | Q(started_at__isnull=True) | Q(ended_at__gte=F("started_at")),
                name="consultation_end_after_start",
            ),
        ]
        indexes = [models.Index(fields=["facility", "status", "scheduled_at"], name="consultation_queue_idx")]


class ConsultationEvent(AppendOnlyModel):
    consultation = models.ForeignKey(Consultation, on_delete=models.PROTECT, related_name="events")
    status = models.CharField(max_length=12, choices=Consultation.Status)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    detail = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField()

    class Meta(AppendOnlyModel.Meta):
        indexes = [models.Index(fields=["consultation", "occurred_at"], name="consultevent_time_idx")]