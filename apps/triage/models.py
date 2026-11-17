from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.core.models import AppendOnlyModel, TimeStampedModel, UUIDModel


class ConcernCategory(UUIDModel):
    """Clinically reviewed taxonomy. Categories used operationally must be approved."""

    taxonomy_version = models.CharField(max_length=30)
    code = models.SlugField(max_length=60)
    label_en = models.CharField(max_length=200)
    label_sw = models.CharField(max_length=200, blank=True)  # needs native-speaker + clinical review
    is_clinically_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["taxonomy_version", "code"], name="concerncategory_unique"),
            models.CheckConstraint(
                condition=Q(is_clinically_approved=False) | Q(approved_by__isnull=False, approved_at__isnull=False),
                name="concerncategory_approval_complete",
            ),
        ]


class RuleSet(TimeStampedModel):
    """Versioned rule-based triage (ported from the prototype). Rules produce SUGGESTIONS only."""

    class Status(models.TextChoices):
        DRAFT = "draft"
        APPROVED = "approved"
        RETIRED = "retired"

    name = models.CharField(max_length=100)
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=8, choices=Status, default=Status.DRAFT)
    definition = models.JSONField(default=dict)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["name", "version"], name="ruleset_unique"),
            models.CheckConstraint(
                condition=~Q(status="approved") | Q(approved_by__isnull=False, approved_at__isnull=False),
                name="ruleset_approved_needs_signoff",
            ),
        ]


class Concern(TimeStampedModel):
    """The unit of review. Also carries callback requests (kind='callback') so they share one
    queue and one response-time KPI. `first_response_at` is set in the same transaction as the
    first PROVIDER decision or provider-sent message. Automated messages (including the urgent
    safety instruction) never set it."""

    class Kind(models.TextChoices):
        CONCERN = "concern"
        CALLBACK = "callback"
        INFO_REQUEST = "info_request"

    class Status(models.TextChoices):
        OPEN = "open"
        IN_REVIEW = "in_review"
        AWAITING_INFO = "awaiting_info"
        ACTIONED = "actioned"
        CLOSED = "closed"

    class SubmittedVia(models.TextChoices):
        MOTHER = "mother"
        CHW = "chw"

    short_code = models.CharField(max_length=12, unique=True)
    kind = models.CharField(max_length=14, choices=Kind, default=Kind.CONCERN)
    mother = models.ForeignKey("mothers.Mother", on_delete=models.PROTECT, related_name="concerns")
    episode = models.ForeignKey("care.PregnancyEpisode", null=True, blank=True, on_delete=models.PROTECT, related_name="concerns")
    conversation = models.ForeignKey("comms.Conversation", null=True, blank=True, on_delete=models.PROTECT, related_name="concerns")
    source_message = models.ForeignKey("comms.Message", null=True, blank=True, on_delete=models.PROTECT, related_name="concerns")
    channel = models.CharField(max_length=10)
    submitted_via = models.CharField(max_length=6, choices=SubmittedVia, default=SubmittedVia.MOTHER)
    submitted_by_chw = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    client_uuid = models.UUIDField(null=True, blank=True)  # offline-sync idempotency
    assigned_facility = models.ForeignKey("facilities.Facility", on_delete=models.PROTECT, related_name="concerns")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=14, choices=Status, default=Status.OPEN)
    submitted_at = models.DateTimeField()  # when the mother/CHW actually raised it
    first_response_at = models.DateTimeField(null=True, blank=True)
    safety_message_sent_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)  # e.g. preferred callback window

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["client_uuid"], condition=Q(client_uuid__isnull=False), name="concern_unique_client_uuid"
            ),
            models.CheckConstraint(
                condition=Q(first_response_at__isnull=True) | Q(first_response_at__gte=F("submitted_at")),
                name="concern_response_after_submission",
            ),
        ]
        indexes = [
            models.Index(
                fields=["assigned_facility", "status", "submitted_at"],
                condition=Q(status__in=["open", "in_review", "awaiting_info"]),
                name="concern_review_queue_idx",
            ),
            models.Index(fields=["mother", "-submitted_at"], name="concern_mother_time_idx"),
        ]


class ConcernSuggestion(AppendOnlyModel):
    """Automated assistance (rules or model). Never part of the clinical record."""

    class Source(models.TextChoices):
        RULES = "rules"
        MODEL = "model"

    class Priority(models.TextChoices):
        ROUTINE = "routine"
        PROMPT = "prompt"

    concern = models.ForeignKey(Concern, on_delete=models.PROTECT, related_name="suggestions")
    source = models.CharField(max_length=5, choices=Source)
    ruleset = models.ForeignKey(RuleSet, null=True, blank=True, on_delete=models.PROTECT, related_name="suggestions")
    model_version = models.ForeignKey("ai.ModelVersion", null=True, blank=True, on_delete=models.PROTECT, related_name="suggestions")
    category = models.ForeignKey(ConcernCategory, null=True, blank=True, on_delete=models.PROTECT, related_name="suggestions")
    suggested_priority = models.CharField(max_length=8, choices=Priority, blank=True)
    uncertain = models.BooleanField(default=False)
    requires_human_review = models.BooleanField(default=True)
    is_shadow = models.BooleanField(default=False)  # shadow-mode output: logged, hidden from the review UI
    confidence = models.FloatField(null=True, blank=True)  # only if calibrated
    payload = models.JSONField(default=dict, blank=True)  # explanation / extracted fields
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    occurred_at = models.DateTimeField()

    class Meta(AppendOnlyModel.Meta):
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(source="rules", ruleset__isnull=False, model_version__isnull=True)
                    | Q(source="model", model_version__isnull=False, ruleset__isnull=True)
                ),
                name="concernsuggestion_source_matches_producer",
            ),
            models.CheckConstraint(condition=Q(requires_human_review=True), name="concernsuggestion_always_human_reviewed"),
        ]
        indexes = [models.Index(fields=["concern", "occurred_at"], name="suggestion_concern_time_idx")]


class ConcernDecision(AppendOnlyModel):
    """The only record of a clinical decision on a concern. Whether a suggestion was confirmed
    or overridden is read from `action` + `suggestion`: there is no separate prediction-review table."""

    class Action(models.TextChoices):
        CLASSIFY = "classify"
        CONFIRM = "confirm"
        OVERRIDE = "override"
        REQUEST_INFO = "request_info"
        CALL = "call"
        ESCALATE = "escalate"
        ACKNOWLEDGE = "acknowledge"  # acknowledges a ConcernEscalation
        REFER = "refer"
        CLOSE = "close"

    concern = models.ForeignKey(Concern, on_delete=models.PROTECT, related_name="decisions")
    provider = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    action = models.CharField(max_length=14, choices=Action)
    suggestion = models.ForeignKey(ConcernSuggestion, null=True, blank=True, on_delete=models.PROTECT, related_name="decisions")
    final_category = models.ForeignKey(ConcernCategory, null=True, blank=True, on_delete=models.PROTECT, related_name="decisions")
    rationale = models.TextField(blank=True)
    call_session = models.ForeignKey("comms.CallSession", null=True, blank=True, on_delete=models.PROTECT, related_name="decisions")
    consultation = models.ForeignKey("comms.Consultation", null=True, blank=True, on_delete=models.PROTECT, related_name="decisions")
    occurred_at = models.DateTimeField()

    class Meta(AppendOnlyModel.Meta):
        constraints = [
            models.CheckConstraint(condition=~Q(action="override") | ~Q(rationale=""), name="concerndecision_override_needs_rationale"),
            models.CheckConstraint(
                condition=~Q(action__in=["confirm", "override"]) | Q(suggestion__isnull=False),
                name="concerndecision_confirm_override_needs_suggestion",
            ),
        ]
        indexes = [models.Index(fields=["concern", "occurred_at"], name="decision_concern_time_idx")]


class ConcernEscalation(AppendOnlyModel):
    class Trigger(models.TextChoices):
        RULE_URGENT = "rule_urgent"
        UNREVIEWED_TIMEOUT = "unreviewed_timeout"
        COMMS_FAILURE = "comms_failure"
        PROVIDER = "provider"

    concern = models.ForeignKey(Concern, on_delete=models.PROTECT, related_name="escalations")
    trigger = models.CharField(max_length=20, choices=Trigger)
    level = models.PositiveSmallIntegerField(default=1)
    notified_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    notified_role = models.CharField(max_length=24, blank=True)
    occurred_at = models.DateTimeField()

    class Meta(AppendOnlyModel.Meta):
        indexes = [models.Index(fields=["concern", "occurred_at"], name="escalation_concern_time_idx")]
