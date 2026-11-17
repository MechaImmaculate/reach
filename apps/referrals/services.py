from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.consent.models import Purpose
from apps.consent.services import require_consent
from apps.mothers.models import MotherFacilityAccess

from .models import Referral, ReferralEvent

S = Referral.Status

TRANSITIONS = {
    S.DRAFT: (S.ISSUED,),
    S.ISSUED: (S.SENT, S.CANCELLED),
    S.SENT: (S.ACKNOWLEDGED, S.DECLINED, S.UNRESOLVED, S.CANCELLED),
    S.ACKNOWLEDGED: (S.ARRIVED, S.DECLINED, S.UNRESOLVED, S.CANCELLED),
    S.ARRIVED: (S.UNDER_ASSESSMENT,),
    S.UNDER_ASSESSMENT: (S.COMPLETED,),
    S.UNRESOLVED: (S.ACKNOWLEDGED, S.ARRIVED, S.COMPLETED, S.CANCELLED),  # late information arrives
    S.COMPLETED: (), S.CANCELLED: (), S.DECLINED: (),  # terminal; a declined referral is replaced, not edited
}
_TIMESTAMP = {S.ISSUED: "issued_at", S.ACKNOWLEDGED: "acknowledged_at",
              S.ARRIVED: "arrived_at", S.COMPLETED: "completed_at"}


class IllegalTransition(Exception):
    pass


def _validate_for_issue(ref):
    if ref.from_facility_id == ref.to_facility_id:
        raise ValueError("Cannot refer to the same facility.")
    v = ref.service_verification
    if v is not None:
        fs = v.facility_service
        if fs.facility_id != ref.to_facility_id or fs.service_id != ref.required_service_id:
            raise ValueError("Verification is not for the destination facility and required service.")
        if v.status not in ("available", "limited") and not ref.override_reason.strip():
            raise ValueError("Destination service is not verified available: an override reason is required.")
    elif not ref.override_reason.strip():
        raise ValueError("Unverified destination: an override reason is required.")
    # [J] emergency referrals are not blocked by missing facility-sharing consent. Confirm with legal review.
    if ref.priority != Referral.Priority.EMERGENCY:
        require_consent(ref.mother_id, Purpose.FACILITY_SHARING)


@transaction.atomic
def transition(referral_id, to_status, *, actor_kind, actor=None, channel="", note="",
               outcome="", occurred_at=None):
    ref = Referral.objects.select_for_update().select_related(
        "service_verification__facility_service").get(pk=referral_id)
    to_status = S(to_status)
    ReferralEvent.ActorKind(actor_kind)
    if to_status not in TRANSITIONS[ref.status]:
        raise IllegalTransition(f"{ref.status} -> {to_status}")
    at = occurred_at or timezone.now()

    if to_status == S.ISSUED:
        _validate_for_issue(ref)
    if to_status == S.COMPLETED:
        outcome = outcome or ref.outcome
        if not outcome.strip():
            raise ValueError("Completing a referral needs a documented outcome.")
        ref.outcome, ref.outcome_recorded_by = outcome, actor
    field = _TIMESTAMP.get(to_status)
    if field and getattr(ref, field) is None:
        setattr(ref, field, at)

    ReferralEvent.objects.create(referral=ref, from_status=ref.status, to_status=to_status,
                                 actor=actor, actor_kind=actor_kind, channel=channel,
                                 note=note, occurred_at=at)
    from_status, ref.status = ref.status, to_status
    ref.save()
    _sync_access(ref, to_status, at, actor)
    return ref


def _sync_access(ref, to_status, at, actor):
    """Receiving facility sees the mother only for the life of the referral (data minimisation)."""
    if to_status == S.ISSUED:
        MotherFacilityAccess.objects.create(
            mother_id=ref.mother_id, facility_id=ref.to_facility_id, kind="referral", granted_by=actor,
            reason=f"Referral {ref.short_code}", source_type="referral", source_ref=ref.pk, valid_from=at)
        return
    open_grants = MotherFacilityAccess.objects.filter(
        source_type="referral", source_ref=ref.pk, valid_to__isnull=True)
    if to_status in (S.CANCELLED, S.DECLINED):
        open_grants.update(valid_to=timezone.now())
    elif to_status == S.COMPLETED:  # [J] grace period so the receiving team can finish documenting
        days = getattr(settings, "REACH_REFERRAL_ACCESS_GRACE_DAYS", 7)
        open_grants.update(valid_to=timezone.now() + timedelta(days=days))