"""Mother-facing pages. A mother only ever sees her own record; every query starts from request.mother."""
from collections import OrderedDict

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.formats import date_format
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.appointments import services as booking
from apps.appointments.models import Appointment
from apps.mothers import services as auth

from .access import mother_required


def _ip(request):
    return request.META.get("REMOTE_ADDR")  # REMOTE_ADDR only; revisit behind a proxy


def signin(request):
    if request.session.get(auth.SESSION_KEY):
        return redirect("web:mother_home")
    error = ""
    if request.method == "POST":
        try:
            phone = auth.clean_phone(request.POST.get("phone", ""))
        except ValueError:
            phone, error = None, "That does not look like a phone number. Try the format 0712 345 678."
        if phone:
            try:
                auth.request_code(phone, ip=_ip(request))
            except auth.OtpDeliveryUnavailable:
                error = ("Sign-in by text message is not connected yet in this proof of concept, "
                         "so we cannot send you a code. Your clinic can still reach you by phone.")
            else:
                request.session["reach_otp_phone"] = phone
                return redirect("web:mother_verify")
    return render(request, "web/mother_signin.html", {"step": "phone", "error": error})


def verify(request):
    phone = request.session.get("reach_otp_phone")
    if not phone:
        return redirect("web:mother_signin")
    error = ""
    if request.method == "POST":
        if request.POST.get("action") == "resend":
            try:
                auth.request_code(phone, ip=_ip(request))
                messages.info(request, "If that number is registered, a new code is on its way.")
            except auth.OtpDeliveryUnavailable:
                error = "We cannot send codes right now."
            else:
                return redirect("web:mother_verify")
        else:
            account = auth.verify_code(phone, request.POST.get("code", ""), ip=_ip(request))
            if account:
                auth.start_session(request, account)
                return redirect("web:mother_home")
            error = "That code did not work. Check it and try again, or ask for a new code."
    shown = phone[:-3].replace("+254", "0") + "***"
    return render(request, "web/mother_signin.html", {"step": "code", "error": error, "shown": shown})


@require_POST
def signout(request):
    auth.end_session(request)
    return redirect("web:home")


def _ctx(request, **extra):
    return {"mother": request.mother, "first_name": (request.mother.full_name or "").split(" ")[0], **extra}


@mother_required
def dashboard(request):
    m, now = request.mother, timezone.now()
    episode = m.episodes.exclude(status__in=["closed", "transferred", "lost_to_followup"]).order_by("-registered_at").first()
    weeks = None
    if episode and episode.status == "active" and episode.lmp_date:
        weeks = (timezone.localdate() - episode.lmp_date).days // 7
    plan = episode.care_plans.order_by("-version").first() if episode else None
    babies = list(episode.newborns.order_by("birth_date")) if episode else []
    for b in babies:
        b.age_days = (timezone.localdate() - b.birth_date).days
    appts = Appointment.objects.filter(mother=m).select_related("facility", "provider").order_by("scheduled_for")
    upcoming = [a for a in appts if a.status in booking.CANCELLABLE and a.scheduled_for >= now]
    past = list(reversed([a for a in appts if a not in upcoming]))[:6]
    for a in upcoming:
        a.can_cancel = a.scheduled_for >= now + booking.LEAD
    return render(request, "web/mother_dashboard.html", _ctx(
        request, episode=episode, weeks=weeks, plan=plan, babies=babies, upcoming=upcoming, past=past))


@mother_required
def book(request):
    m = request.mother
    if request.method == "POST":
        try:
            appt = booking.book_slot(m, request.POST.get("slot", ""), request.POST.get("type", ""))
        except booking.BookingError as e:
            messages.error(request, str(e))
            return redirect("web:mother_book")
        messages.success(request, f"Your visit is booked for {date_format(timezone.localtime(appt.scheduled_for), 'l j F')} at {date_format(timezone.localtime(appt.scheduled_for), 'H:i')} at {appt.facility.name}.")
        return redirect("web:mother_home")
    days = OrderedDict()
    for s in booking.open_slots(m)[:80]:
        days.setdefault(timezone.localtime(s.starts_at).date(), []).append(s)
    episode = m.episodes.filter(status__in=["active", "delivered", "postnatal"]).order_by("-registered_at").first()
    default_type = "anc" if episode and episode.status == "active" else "pnc"
    types = [(v, l) for v, l in Appointment.Type.choices if v != "other"]
    return render(request, "web/mother_book.html", _ctx(request, days=days.items(), types=types, default_type=default_type))


@require_POST
@mother_required
def cancel(request):
    try:
        booking.cancel_appointment(request.mother, request.POST.get("appointment", ""))
        messages.success(request, "Your visit was cancelled.")
    except booking.BookingError as e:
        messages.error(request, str(e))
    return redirect("web:mother_home")
