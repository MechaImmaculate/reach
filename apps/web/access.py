"""Workspace routing and facility scoping for the signed-in app. No business data here."""
from functools import wraps

from django.shortcuts import redirect
from django.urls import reverse

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from apps.facilities.access import active_memberships
from apps.facilities.models import Role

SESSION_KEY = "reach_active_facility"

WORKSPACES = {
    "clinician": {
        "label": "Clinician", "url": "web:clinician", "roles": {Role.CLINICIAN},
        "title": "Clinician overview",
        "blurb": "Concerns, referrals and follow-up for the facility you are working at.",
        "scope_note": "You can see mothers with an active access grant at your facilities. Every access is logged.",
    },
    "chw": {
        "label": "Community health worker", "url": "web:chw", "roles": {Role.CHW},
        "title": "Community health worker",
        "blurb": "Your assigned mothers, visits and follow-up tasks.",
        "scope_note": "You see only mothers currently assigned to you, through a limited view. You do not see clinical records.",
    },
    "facility": {
        "label": "Facility", "url": "web:facility", "roles": {Role.FACILITY_ADMIN, Role.REFERRAL_COORDINATOR},
        "title": "Facility operations",
        "blurb": "Referrals, services and providers for your facility.",
        "scope_note": "You manage facility operations and referrals. Clinical decisions stay with clinicians.",
    },
    "county": {
        "label": "County", "url": "web:county", "roles": {Role.COUNTY_ADMIN},
        "title": "County overview",
        "blurb": "Coverage, service availability and follow-up trends for your county.",
        "scope_note": "You see aggregated figures only. Individual mothers and households are never shown here.",
    },
    "system": {
        "label": "System administration", "url": "web:system", "roles": {Role.SYSTEM_ADMIN},
        "title": "System administration",
        "blurb": "Accounts, configuration and technical health.",
        "scope_note": "System administration does not include access to clinical records.",
    },
}

# (label, url name or None). None renders as a disabled "Soon" item: honest about what is not built.
NAV = {
    "clinician": [("Overview", "web:clinician"), ("Review queue", None), ("Mothers", None), ("Consultations", None),
                  ("Appointments", "web:clinician_schedule"), ("Referrals", None), ("Follow-up tasks", None), ("Facility map", None)],
    "chw": [("Overview", "web:chw"), ("Assigned mothers", None), ("Community visits", None),
            ("Report a concern", None), ("Follow-up tasks", None)],
    "facility": [("Overview", "web:facility"), ("Referral board", None), ("Services", None),
                 ("Providers", None), ("Reports", None)],
    "county": [("Overview", "web:county"), ("Coverage map", None), ("Facilities", None),
               ("Indicators", None), ("Reports", None)],
    "system": [("Overview", "web:system")],
}


def workspaces_for(user):
    roles = set(active_memberships(user).values_list("role", flat=True))
    return [key for key, w in WORKSPACES.items() if roles & w["roles"]]


def facilities_for(user, workspace):
    qs = (active_memberships(user, roles=WORKSPACES[workspace]["roles"])
          .exclude(facility__isnull=True).select_related("facility"))
    unique = {m.facility_id: m.facility for m in qs}
    return sorted(unique.values(), key=lambda f: f.name)


def pick_active(request, facilities):
    wanted = request.session.get(SESSION_KEY)
    for f in facilities:
        if str(f.pk) == wanted:
            return f
    return facilities[0] if facilities else None


def workspace_required(key):
    """Login + a currently valid membership for this workspace, else 403. Sets request.* for the view."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            mine = workspaces_for(request.user)
            if key not in mine:
                raise PermissionDenied
            request.workspace, request.my_workspaces = key, mine
            request.facilities = facilities_for(request.user, key)
            request.active_facility = pick_active(request, request.facilities)
            return view(request, *args, **kwargs)
        return login_required(wrapper)
    return decorator


def mother_required(view):
    """A mother session only (separate from staff login). Sets request.mother_account / request.mother."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        from apps.mothers.models import MotherAccount
        from apps.mothers.services import SESSION_KEY as MOTHER_KEY
        pk = request.session.get(MOTHER_KEY)
        account = None
        if pk:
            try:
                account = (MotherAccount.objects.select_related("mother")
                           .filter(pk=pk, status="active", mother__merged_into__isnull=True, mother__status="active").first())
            except (ValueError, TypeError):
                account = None
        if account is None:
            request.session.pop(MOTHER_KEY, None)
            return redirect(reverse("web:mother_signin"))
        request.mother_account, request.mother = account, account.mother
        return view(request, *args, **kwargs)
    return wrapper
