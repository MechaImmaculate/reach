from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.core.models import AppendOnlyModel, TimeStampedModel


class AvailabilitySlot(TimeStampedModel):
    """A bookable block of a provider's time at a facility. Published by the provider; a slot is
    taken when a live Appointment points at it (enforced by a partial unique constraint)."""

    class Mode(models.TextChoices):
        IN_PERSON = "in_person"
        AUDIO = "audio"
        VIDEO = "video"

    class Status(models.TextChoices):
        OPEN = "open"
        CLOSED = "closed"

    provider = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="availability_slots")
    facility = models.ForeignKey("facilities.Facility", on_delete=models.PROTECT, related_name="availability_slots")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    mode = models.CharField(max_length=10, choices=Mode, default=Mode.IN_PERSON)
    status = models.CharField(max_length=8, choices=Status, default=Status.OPEN)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(ends_at__gt=F("starts_at")), name="slot_ends_after_start"),
            models.UniqueConstraint(fields=["provider", "starts_at"], name="slot_unique_provider_start"),
        ]
        indexes = [models.Index(fields=["facility", "status", "starts_at"], name="slot_facility_status_time_idx")]


class Appointment(TimeStampedModel):
    """A reminder is not attendance. Attendance is an explicit event recorded by the facility."""

    class Type(models.TextChoices):
        ANC = "anc"
        PNC = "pnc"
        NEWBORN = "newborn"
        OTHER = "other"

    class Status(models.TextChoices):
        SCHEDULED = "scheduled"
        CONFIRMED = "confirmed"
        ATTENDED = "attended"
        MISSED = "missed"
        CANCELLED = "cancelled"
        RESCHEDULED = "rescheduled"

    mother = models.ForeignKey("mothers.Mother", on_delete=models.PROTECT, related_name="appointments")
    episode = models.ForeignKey("care.PregnancyEpisode", on_delete=models.PROTECT, related_name="appointments")
    facility = models.ForeignKey("facilities.Facility", on_delete=models.PROTECT, related_name="appointments")
    provider = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    type = models.CharField(max_length=10, choices=Type)
    purpose = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=12, choices=Status, default=Status.SCHEDULED)
    scheduled_for = models.DateTimeField()
    mode = models.CharField(max_length=10, choices=AvailabilitySlot.Mode, default=AvailabilitySlot.Mode.IN_PERSON)
    slot = models.ForeignKey(AvailabilitySlot, null=True, blank=True, on_delete=models.PROTECT, related_name="appointments")
    rescheduled_from = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="rescheduled_to")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["slot"], condition=Q(status__in=["scheduled", "confirmed", "attended"]),
                name="appointment_one_live_per_slot"),
        ]
        indexes = [
            models.Index(fields=["episode", "scheduled_for"], name="appointment_episode_time_idx"),
            models.Index(fields=["facility", "status", "scheduled_for"], name="appointment_facility_idx"),
        ]


class AppointmentEvent(AppendOnlyModel):
    class EventType(models.TextChoices):
        CREATED = "created"
        REMINDER_SENT = "reminder_sent"
        CONFIRMED = "confirmed"
        ATTENDED = "attended"
        MISSED = "missed"
        CANCELLED = "cancelled"
        RESCHEDULED = "rescheduled"

    appointment = models.ForeignKey(Appointment, on_delete=models.PROTECT, related_name="events")
    event_type = models.CharField(max_length=14, choices=EventType)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    channel = models.CharField(max_length=10, blank=True)
    note = models.CharField(max_length=300, blank=True)  # e.g. cancellation reason; never a blame label
    occurred_at = models.DateTimeField()

    class Meta(AppendOnlyModel.Meta):
        indexes = [models.Index(fields=["appointment", "occurred_at"], name="appointmentevent_time_idx")]
