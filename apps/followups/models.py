from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import AppendOnlyModel, TimeStampedModel

_ORIGINS = ("concern", "referral", "appointment", "care_plan")


def _exactly_one_origin():
    """Exactly one origin FK set (D-16: no GenericForeignKey)."""
    clauses = []
    for chosen in _ORIGINS:
        q = Q(**{f"{chosen}__isnull": False})
        for other in _ORIGINS:
            if other != chosen:
                q &= Q(**{f"{other}__isnull": True})
        clauses.append(q)
    combined = clauses[0]
    for q in clauses[1:]:
        combined |= q
    return combined


class FollowUpTask(TimeStampedModel):
    """`overdue` is intentionally NOT a status: it is derived (open and due_at < now)."""

    class Type(models.TextChoices):
        CALL_MOTHER = "call_mother"
        HOME_VISIT = "home_visit"
        CONFIRM_ATTENDANCE = "confirm_attendance"
        CONFIRM_REFERRAL_ARRIVAL = "confirm_referral_arrival"
        CHASE_ACKNOWLEDGEMENT = "chase_acknowledgement"
        OTHER = "other"

    class Status(models.TextChoices):
        PENDING = "pending"
        ASSIGNED = "assigned"
        IN_PROGRESS = "in_progress"
        COMPLETED = "completed"
        UNABLE = "unable"
        CANCELLED = "cancelled"

    OPEN_STATUSES = ("pending", "assigned", "in_progress")

    mother = models.ForeignKey("mothers.Mother", on_delete=models.PROTECT, related_name="followup_tasks")
    episode = models.ForeignKey("care.PregnancyEpisode", null=True, blank=True, on_delete=models.PROTECT, related_name="followup_tasks")
    facility = models.ForeignKey("facilities.Facility", on_delete=models.PROTECT, related_name="followup_tasks")
    concern = models.ForeignKey("triage.Concern", null=True, blank=True, on_delete=models.PROTECT, related_name="followups")
    referral = models.ForeignKey("referrals.Referral", null=True, blank=True, on_delete=models.PROTECT, related_name="followups")
    appointment = models.ForeignKey("appointments.Appointment", null=True, blank=True, on_delete=models.PROTECT, related_name="followups")
    care_plan = models.ForeignKey("care.CarePlan", null=True, blank=True, on_delete=models.PROTECT, related_name="followups")
    task_type = models.CharField(max_length=26, choices=Type)
    assigned_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="assigned_tasks")
    assigned_role = models.CharField(max_length=24, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    protocol_ref = models.CharField(max_length=200, blank=True)  # approved facility protocol that triggered it
    due_at = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status, default=Status.PENDING)
    outcome = models.TextField(blank=True)
    client_uuid = models.UUIDField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=_exactly_one_origin(), name="followuptask_exactly_one_origin"),
            models.UniqueConstraint(
                fields=["client_uuid"], condition=Q(client_uuid__isnull=False), name="followuptask_unique_client_uuid"
            ),
        ]
        indexes = [
            models.Index(
                fields=["due_at"],
                condition=Q(status__in=["pending", "assigned", "in_progress"]),
                name="followuptask_open_due_idx",
            ),
            models.Index(fields=["assigned_user", "status"], name="followuptask_assignee_idx"),
        ]


class FollowUpEvent(AppendOnlyModel):
    task = models.ForeignKey(FollowUpTask, on_delete=models.PROTECT, related_name="events")
    to_status = models.CharField(max_length=12, choices=FollowUpTask.Status)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    note = models.TextField(blank=True)
    client_uuid = models.UUIDField(null=True, blank=True)  # offline-sync idempotency
    occurred_at = models.DateTimeField()

    class Meta(AppendOnlyModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["client_uuid"], condition=Q(client_uuid__isnull=False), name="followupevent_unique_client_uuid"
            ),
        ]
        indexes = [models.Index(fields=["task", "occurred_at"], name="followupevent_time_idx")]
