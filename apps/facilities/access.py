"""Facility-scoped access helpers. Every patient-data queryset goes through these."""
from django.db.models import Q
from django.utils import timezone

from .models import MOTHER_VISIBLE_ROLES, Membership


def active_memberships(user, roles=None):
    now = timezone.now()
    qs = Membership.objects.filter(user=user, is_active=True, valid_from__lte=now).filter(
        Q(valid_to__isnull=True) | Q(valid_to__gt=now)
    )
    if roles:
        qs = qs.filter(role__in=roles)
    return qs


def facility_ids_for(user, roles=None):
    """Subquery of facility ids the user is currently a member of (optionally for given roles)."""
    return active_memberships(user, roles).exclude(facility__isnull=True).values("facility_id")


def mother_visible_facility_ids(user):
    return facility_ids_for(user, MOTHER_VISIBLE_ROLES)
