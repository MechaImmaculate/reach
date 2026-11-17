from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.models import AppendOnlyModel, TimeStampedModel


class CHWAssignment(TimeStampedModel):
    """Drives CHW visibility: a CHW sees only currently assigned mothers (and only a restricted
    serializer of them), never the raw clinical record."""

    chw = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="chw_assignments_made")
    mother = models.ForeignKey("mothers.Mother", on_delete=models.CASCADE, related_name="chw_assignments")
    community = models.ForeignKey("geo.AdminArea", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    valid_from = models.DateTimeField(default=timezone.now)
    valid_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True) | Q(valid_to__gt=F("valid_from")),
                name="chwassignment_valid_range",
            ),
        ]
        indexes = [models.Index(fields=["chw", "valid_to"], name="chwassignment_chw_idx")]


class CommunityVisit(AppendOnlyModel):
    """Recorded possibly offline. `client_uuid` makes re-sync idempotent; `occurred_at` is the
    real visit time and `recorded_at` is when the server received it."""

    class Outcome(models.TextChoices):
        SEEN = "seen"
        NOT_HOME = "not_home"
        REFUSED = "refused"
        REFERRED = "referred"

    assignment = models.ForeignKey(CHWAssignment, on_delete=models.PROTECT, related_name="visits")
    outcome = models.CharField(max_length=10, choices=Outcome)
    notes = models.TextField(blank=True)
    client_uuid = models.UUIDField(null=True, blank=True)
    device_id = models.CharField(max_length=100, blank=True)
    occurred_at = models.DateTimeField()

    class Meta(AppendOnlyModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["client_uuid"], condition=Q(client_uuid__isnull=False), name="communityvisit_unique_client_uuid"
            ),
        ]
        indexes = [models.Index(fields=["assignment", "-occurred_at"], name="communityvisit_time_idx")]
