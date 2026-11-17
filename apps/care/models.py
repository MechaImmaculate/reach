from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import AppendOnlyModel, TimeStampedModel


class PregnancyEpisode(TimeStampedModel):
    """One pregnancy. A mother has one identity but many episodes; history is never overwritten.
    Clinical fields are entered or verified by authorised providers only."""

    class Status(models.TextChoices):
        ACTIVE = "active"
        DELIVERED = "delivered"
        POSTNATAL = "postnatal"
        CLOSED = "closed"
        LOST_TO_FOLLOWUP = "lost_to_followup"
        TRANSFERRED = "transferred"

    mother = models.ForeignKey("mothers.Mother", on_delete=models.PROTECT, related_name="episodes")
    facility = models.ForeignKey("facilities.Facility", on_delete=models.PROTECT, related_name="episodes")
    responsible_provider = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=20, choices=Status, default=Status.ACTIVE)
    lmp_date = models.DateField(null=True, blank=True)
    edd_date = models.DateField(null=True, blank=True)
    gravida = models.PositiveSmallIntegerField(null=True, blank=True)
    parity = models.PositiveSmallIntegerField(null=True, blank=True)
    registered_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)
    closure_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["mother"],
                condition=Q(status="active"),
                name="pregnancyepisode_one_active_per_mother",
            ),
            models.CheckConstraint(
                condition=~Q(status__in=["closed", "lost_to_followup", "transferred"]) | Q(closed_at__isnull=False),
                name="pregnancyepisode_closed_needs_closed_at",
            ),
        ]
        indexes = [models.Index(fields=["facility", "status"], name="episode_facility_status_idx")]


class CarePlan(AppendOnlyModel):
    """Each revision is a new version. Current = highest version for the episode."""

    episode = models.ForeignKey(PregnancyEpisode, on_delete=models.PROTECT, related_name="care_plans")
    version = models.PositiveIntegerField()
    summary = models.TextField(blank=True)
    items = models.JSONField(default=list)  # structured plan items entered by the clinician
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    occurred_at = models.DateTimeField()

    class Meta(AppendOnlyModel.Meta):
        constraints = [models.UniqueConstraint(fields=["episode", "version"], name="careplan_unique_version")]


class ClinicalObservation(AppendOnlyModel):
    """A correction is a new row whose `corrects` points at the row it supersedes."""

    class Source(models.TextChoices):
        PROVIDER = "provider"
        CHW = "chw"
        MOTHER_REPORTED = "mother_reported"

    episode = models.ForeignKey(PregnancyEpisode, on_delete=models.PROTECT, related_name="observations")
    code = models.CharField(max_length=60)  # agreed clinical data model code
    value = models.JSONField()
    unit = models.CharField(max_length=20, blank=True)
    source = models.CharField(max_length=16, choices=Source)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    corrects = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="corrections")
    occurred_at = models.DateTimeField()

    class Meta(AppendOnlyModel.Meta):
        indexes = [models.Index(fields=["episode", "code", "-occurred_at"], name="observation_episode_code_idx")]


class DeliveryOutcome(TimeStampedModel):
    episode = models.OneToOneField(PregnancyEpisode, on_delete=models.PROTECT, related_name="delivery")
    facility = models.ForeignKey("facilities.Facility", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    delivered_at = models.DateTimeField()
    mode = models.CharField(max_length=40, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")


class Newborn(TimeStampedModel):
    """Kept separate from the mother's record, linked through the episode (SRS 2.2)."""

    class Status(models.TextChoices):
        ACTIVE = "active"
        TRANSFERRED = "transferred"
        CLOSED = "closed"

    episode = models.ForeignKey(PregnancyEpisode, on_delete=models.PROTECT, related_name="newborns")
    birth_date = models.DateField()
    sex = models.CharField(max_length=10, blank=True)
    status = models.CharField(max_length=12, choices=Status, default=Status.ACTIVE)
    registered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
