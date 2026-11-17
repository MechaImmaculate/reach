from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.core.models import AppendOnlyModel, TimeStampedModel, UUIDModel


class Referral(TimeStampedModel):
    """A referral has a lifecycle, not a button. `status` is denormalised from ReferralEvent
    (same transaction). Transitions are validated in referrals/services.py."""

    class Status(models.TextChoices):
        DRAFT = "draft"
        ISSUED = "issued"
        SENT = "sent"
        ACKNOWLEDGED = "acknowledged"
        ARRIVED = "arrived"
        UNDER_ASSESSMENT = "under_assessment"
        COMPLETED = "completed"
        CANCELLED = "cancelled"
        DECLINED = "declined"
        UNRESOLVED = "unresolved"

    class Priority(models.TextChoices):  # set by the clinician, never by software
        ROUTINE = "routine"
        URGENT = "urgent"
        EMERGENCY = "emergency"

    class EstimateMethod(models.TextChoices):
        STRAIGHT_LINE = "straight_line"
        ROAD_NETWORK = "road_network"
        REPORTED = "reported"

    short_code = models.CharField(max_length=12, unique=True)  # "reply YES R-4F7K2M"
    mother = models.ForeignKey("mothers.Mother", on_delete=models.PROTECT, related_name="referrals")
    episode = models.ForeignKey("care.PregnancyEpisode", null=True, blank=True, on_delete=models.PROTECT, related_name="referrals")
    concern = models.ForeignKey("triage.Concern", null=True, blank=True, on_delete=models.PROTECT, related_name="referrals")
    consultation = models.ForeignKey("comms.Consultation", null=True, blank=True, on_delete=models.PROTECT, related_name="referrals")
    from_facility = models.ForeignKey("facilities.Facility", on_delete=models.PROTECT, related_name="referrals_out")
    to_facility = models.ForeignKey("facilities.Facility", on_delete=models.PROTECT, related_name="referrals_in")
    referring_provider = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    required_service = models.ForeignKey("facilities.Service", on_delete=models.PROTECT, related_name="+")
    # Snapshot of the verification relied on at issue time: answers "why did we send her there?"
    service_verification = models.ForeignKey(
        "facilities.FacilityServiceVerification", null=True, blank=True, on_delete=models.PROTECT, related_name="referrals"
    )
    override_reason = models.TextField(blank=True)  # required when the destination is unverified
    clinical_reason = models.TextField()
    priority = models.CharField(max_length=10, choices=Priority, default=Priority.ROUTINE)
    status = models.CharField(max_length=18, choices=Status, default=Status.DRAFT)
    issued_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    arrived_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    outcome = models.TextField(blank=True)
    outcome_recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    # Estimates only: never display as an actual journey time.
    est_distance_m = models.PositiveIntegerField(null=True, blank=True)
    est_travel_seconds = models.PositiveIntegerField(null=True, blank=True)
    est_method = models.CharField(max_length=14, choices=EstimateMethod, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=~Q(from_facility=F("to_facility")), name="referral_distinct_facilities"),
            models.CheckConstraint(
                condition=Q(service_verification__isnull=False) | ~Q(override_reason=""),
                name="referral_unverified_destination_needs_override_reason",
            ),
            models.CheckConstraint(
                condition=(
                    Q(est_distance_m__isnull=True, est_travel_seconds__isnull=True, est_method="")
                    | (Q(est_distance_m__isnull=False, est_travel_seconds__isnull=False) & ~Q(est_method=""))
                ),
                name="referral_estimate_all_or_none",
            ),
            models.CheckConstraint(
                condition=Q(status="draft") | Q(issued_at__isnull=False),
                name="referral_issued_at_once_issued",
            ),
        ]
        indexes = [
            models.Index(fields=["to_facility", "status"], name="referral_incoming_idx"),
            models.Index(fields=["from_facility", "status"], name="referral_outgoing_idx"),
            models.Index(
                fields=["status", "issued_at"],
                condition=Q(status__in=["issued", "sent", "acknowledged", "unresolved"]),
                name="referral_open_idx",
            ),
        ]


class ReferralEvent(AppendOnlyModel):
    class ActorKind(models.TextChoices):
        PROVIDER = "provider"
        RECEIVING_FACILITY = "receiving_facility"
        MOTHER = "mother"
        CHW = "chw"
        SYSTEM = "system"

    referral = models.ForeignKey(Referral, on_delete=models.PROTECT, related_name="events")
    from_status = models.CharField(max_length=18, choices=Referral.Status, blank=True)
    to_status = models.CharField(max_length=18, choices=Referral.Status)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    actor_kind = models.CharField(max_length=20, choices=ActorKind)
    channel = models.CharField(max_length=10, blank=True)  # how acknowledgement arrived: portal, sms, phone
    note = models.TextField(blank=True)
    occurred_at = models.DateTimeField()

    class Meta(AppendOnlyModel.Meta):
        indexes = [models.Index(fields=["referral", "occurred_at"], name="referralevent_time_idx")]


class ReferralDocument(UUIDModel):
    referral = models.ForeignKey(Referral, on_delete=models.PROTECT, related_name="documents")
    kind = models.CharField(max_length=40)
    file_ref = models.CharField(max_length=300)  # key in PRIVATE object storage, never a public URL
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    uploaded_at = models.DateTimeField()
