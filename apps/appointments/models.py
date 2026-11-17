from django.conf import settings
from django.db import models

from apps.core.models import AppendOnlyModel, TimeStampedModel


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
    rescheduled_from = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="rescheduled_to")

    class Meta:
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
