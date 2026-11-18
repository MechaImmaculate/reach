from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.facilities.access import active_memberships
from apps.followups.models import FollowUpTask
from apps.mothers.models import Mother
from apps.referrals.models import Referral
from apps.triage.models import Concern

from apps.appointments import services as booking
from apps.appointments.models import Appointment, AvailabilitySlot

from .access import (NAV, SESSION_KEY, WORKSPACES, facilities_for, workspace_required, workspaces_for)


def home(request):
    """Public, static landing page. No database access, no personal data."""
    return render(request, "web/home.html", {"contact_email": getattr(settings, "REACH_CONTACT_EMAIL", "")})


class ReachLoginView(LoginView):
    template_name = "web/login.html"
    redirect_authenticated_user = True

    def get_default_redirect_url(self):
        return reverse("web:landing")

    def form_valid(self, form):
        self.request.session.pop("reach_mother_id", None)  # never keep a mother session beside a staff one
        return super().form_valid(form)


@login_required
def landing(request):
    """Send the user to their workspace, or let them choose when they have several."""
    keys = workspaces_for(request.user)
    if len(keys) == 1:
        return redirect(WORKSPACES[keys[0]]["url"])
    return render(request, "web/picker.html", {"choices": [(k, WORKSPACES[k]) for k in keys]})


@require_POST
@login_required
def switch_facility(request):
    ws, fid = request.POST.get("workspace"), request.POST.get("facility")
    if ws in WORKSPACES and ws in workspaces_for(request.user):
        if fid in {str(f.pk) for f in facilities_for(request.user, ws)}:
            request.session[SESSION_KEY] = fid
    nxt = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        nxt = reverse("web:landing")
    return redirect(nxt)


def _ctx(request, **extra):
    key = request.workspace
    return {
        "workspace_key": key, "ws": WORKSPACES[key], "nav": NAV[key],
        "current": request.resolver_match.view_name,
        "my_workspaces": [(k, WORKSPACES[k]) for k in request.my_workspaces],
        "facilities": request.facilities, "active_facility": request.active_facility,
        "memberships": active_memberships(request.user).select_related("facility", "admin_area"),
        **extra,
    }


def _render(request, template="web/workspace.html", **extra):
    return render(request, template, _ctx(request, **extra))


@workspace_required("clinician")
def clinician(request):
    fac, now = request.active_facility, timezone.now()
    tiles = [
        {"label": "Mothers registered here",
         "value": Mother.objects.visible_to(request.user).filter(registered_facility=fac).count()},
        {"label": "Concerns awaiting review",
         "value": Concern.objects.filter(assigned_facility=fac, status__in=["open", "in_review", "awaiting_info"]).count()},
        {"label": "No provider response yet",
         "value": Concern.objects.filter(assigned_facility=fac, first_response_at__isnull=True).exclude(status="closed").count(),
         "note": "The first-response clock starts at submission."},
        {"label": "Referrals in progress",
         "value": Referral.objects.filter(from_facility=fac, status__in=["issued", "sent", "acknowledged", "unresolved"]).count()},
        {"label": "Overdue follow-ups",
         "value": FollowUpTask.objects.filter(facility=fac, status__in=FollowUpTask.OPEN_STATUSES, due_at__lt=now).count(),
         "note": "Operational flag, not clinical urgency."},
    ]
    return _render(request, tiles=tiles)


@workspace_required("chw")
def chw(request):
    return _render(request)


@workspace_required("facility")
def facility(request):
    return _render(request)


@workspace_required("county")
def county(request):
    return _render(request)


@workspace_required("system")
def system(request):
    return _render(request)


def _parse_slot_form(post):
    from datetime import date, time
    try:
        return (date.fromisoformat(post.get("day", "")), time.fromisoformat(post.get("start", "")),
                time.fromisoformat(post.get("end", "")), int(post.get("minutes", "")), post.get("mode", "in_person"))
    except ValueError:
        raise ValueError("Please fill in the date, start time, end time and slot length.")


@workspace_required("clinician")
def clinician_schedule(request):
    fac, user, now = request.active_facility, request.user, timezone.now()
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if fac is None:
                raise ValueError("You have no active facility.")
            if action == "add":
                day, start, end, minutes, mode = _parse_slot_form(request.POST)
                if mode not in booking.enabled_modes():
                    raise ValueError("That visit mode is not available yet.")
                n = booking.create_slots(user, fac, day, start, end, minutes, mode)
                messages.success(request, f"Published {n} new slot{'s' if n != 1 else ''}." if n else "Those slots already exist.")
            elif action == "close":
                booking.close_slot(user, request.POST.get("slot", ""))
                messages.success(request, "Slot closed.")
        except (ValueError, booking.BookingError) as e:
            messages.error(request, str(e))
        return redirect("web:clinician_schedule")
    profile = getattr(user, "provider_profile", None)
    slots = (AvailabilitySlot.objects.filter(provider=user, facility=fac, status="open", starts_at__gte=now)
             .prefetch_related("appointments").order_by("starts_at")[:60])
    slot_rows = [{"slot": s, "taken": any(a.status in booking.LIVE for a in s.appointments.all())} for s in slots]
    visible = Mother.objects.visible_to(user).values("pk")
    appts = (Appointment.objects.filter(facility=fac, status__in=booking.LIVE, scheduled_for__gte=now - timedelta(days=1),
                                        mother__in=visible).select_related("mother", "provider").order_by("scheduled_for")[:50])
    return _render(request, template="web/clinician_schedule.html", slot_rows=slot_rows, appts=appts,
                   verified=bool(profile and profile.verification_status == "verified"),
                   modes=[(v, l) for v, l in AvailabilitySlot.Mode.choices if v in booking.enabled_modes()],
                   minutes=booking.SLOT_MINUTES)