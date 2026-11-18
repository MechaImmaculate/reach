"""Availability and booking. All rules live here; views only call these functions.

Live appointment = scheduled, confirmed or attended. A slot with a live appointment is taken.
"""
from datetime import datetime, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.mothers.models import MotherFacilityAccess

from .models import Appointment, AppointmentEvent, AvailabilitySlot

LIVE = ["scheduled", "confirmed", "attended"]
CANCELLABLE = ["scheduled", "confirmed"]
LEAD = timedelta(hours=2)          # [J] booking and cancelling close this long before the slot
BOOKING_WINDOW_DAYS = 21
SLOT_MINUTES = (15, 20, 30, 45, 60)
BOOKABLE_ACCESS_KINDS = ["primary", "shared_care", "consultation"]  # not referral-only grants


class BookingError(Exception):
    """Message is safe to show to the person."""


def enabled_modes():
    return list(getattr(settings, "REACH_ENABLED_MODES", ["in_person"]))


def _mother_episode(mother):
    return (mother.episodes.filter(status__in=["active", "delivered", "postnatal"])
            .order_by("-registered_at").first())


def open_slots(mother):
    """Slots this mother may book: verified provider, facility she has an active access grant at,
    in the future beyond the lead time, not already taken, in an enabled mode."""
    now = timezone.now()
    facility_ids = (MotherFacilityAccess.objects
                    .filter(mother=mother, kind__in=BOOKABLE_ACCESS_KINDS, valid_from__lte=now)
                    .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=now)).values("facility_id"))
    return (AvailabilitySlot.objects
            .filter(status="open", facility_id__in=facility_ids, mode__in=enabled_modes(),
                    starts_at__gte=now + LEAD, starts_at__lt=now + timedelta(days=BOOKING_WINDOW_DAYS),
                    provider__provider_profile__verification_status="verified",
                    provider__is_active=True)
            .exclude(appointments__status__in=LIVE)
            .select_related("provider", "facility").order_by("starts_at"))


@transaction.atomic
def book_slot(mother, slot_id, appt_type):
    now = timezone.now()
    if appt_type not in Appointment.Type.values:
        raise BookingError("Please choose a type of visit.")
    try:
        slot = AvailabilitySlot.objects.select_for_update(of=("self",)).get(pk=slot_id)
    except (AvailabilitySlot.DoesNotExist, ValueError, TypeError):
        raise BookingError("That time is no longer available.")
    if slot.pk not in set(open_slots(mother).values_list("pk", flat=True)):
        raise BookingError("That time is no longer available.")
    episode = _mother_episode(mother)
    if episode is None:
        raise BookingError("Your clinic needs to register your pregnancy or recovery before you can book here. Please contact them.")
    clash = Appointment.objects.filter(mother=mother, status__in=LIVE).filter(
        Q(slot__starts_at__lt=slot.ends_at, slot__ends_at__gt=slot.starts_at)
        | Q(slot__isnull=True, scheduled_for__gte=slot.starts_at, scheduled_for__lt=slot.ends_at)).exists()
    if clash:
        raise BookingError("You already have a visit around that time.")
    try:
        with transaction.atomic():
            appt = Appointment.objects.create(
                mother=mother, episode=episode, facility=slot.facility, provider=slot.provider,
                type=appt_type, status="scheduled", scheduled_for=slot.starts_at, mode=slot.mode, slot=slot)
    except IntegrityError:
        raise BookingError("That time was just taken. Please choose another.")
    AppointmentEvent.objects.create(appointment=appt, event_type="created", channel="mother_web", occurred_at=now)
    return appt


@transaction.atomic
def cancel_appointment(mother, appointment_id):
    now = timezone.now()
    try:
        appt = Appointment.objects.select_for_update().get(pk=appointment_id, mother=mother)
    except (Appointment.DoesNotExist, ValueError):
        raise BookingError("We could not find that visit.")
    if appt.status not in CANCELLABLE:
        raise BookingError("This visit can no longer be cancelled.")
    if appt.scheduled_for < now + LEAD:
        raise BookingError("It is too close to the visit time to cancel here. Please call your clinic.")
    appt.status = "cancelled"
    appt.save(update_fields=["status", "updated_at"])
    AppointmentEvent.objects.create(appointment=appt, event_type="cancelled", channel="mother_web",
                                    note="cancelled by mother", occurred_at=now)
    return appt


def create_slots(provider, facility, day, start, end, minutes, mode="in_person"):
    """Publish consecutive slots for one day. day: date, start/end: time. Returns how many were created."""
    if minutes not in SLOT_MINUTES:
        raise ValueError("Choose a slot length from the list.")
    if mode not in AvailabilitySlot.Mode.values:
        raise ValueError("Choose a valid visit mode.")
    tz = timezone.get_current_timezone()
    t0, t1 = datetime.combine(day, start, tz), datetime.combine(day, end, tz)
    if t1 <= t0:
        raise ValueError("The end time must be after the start time.")
    if t1 - t0 > timedelta(hours=10):
        raise ValueError("Please publish at most 10 hours at a time.")
    if t0 < timezone.now():
        raise ValueError("That time is in the past.")
    step, rows, cur = timedelta(minutes=minutes), [], t0
    while cur + step <= t1:
        rows.append(AvailabilitySlot(provider=provider, facility=facility, starts_at=cur, ends_at=cur + step, mode=mode))
        cur += step
    if not rows:
        raise ValueError("That window is shorter than one slot.")
    before = AvailabilitySlot.objects.filter(provider=provider).count()
    AvailabilitySlot.objects.bulk_create(rows, ignore_conflicts=True)  # unique (provider, starts_at) skips duplicates
    return AvailabilitySlot.objects.filter(provider=provider).count() - before


@transaction.atomic
def close_slot(provider, slot_id):
    try:
        slot = AvailabilitySlot.objects.select_for_update().get(pk=slot_id, provider=provider)
    except (AvailabilitySlot.DoesNotExist, ValueError):
        raise BookingError("We could not find that slot.")
    if slot.appointments.filter(status__in=LIVE).exists():
        raise BookingError("A mother has booked this slot. Cancel or reschedule her visit first.")
    slot.status = "closed"
    slot.save(update_fields=["status", "updated_at"])
