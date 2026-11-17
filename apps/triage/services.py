from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.facilities.access import facility_ids_for
from apps.facilities.models import Role

from .models import Concern, ConcernDecision

S = Concern.Status
A = ConcernDecision.Action

TRANSITIONS = {
    S.OPEN: (S.IN_REVIEW, S.AWAITING_INFO, S.ACTIONED, S.CLOSED),
    S.IN_REVIEW: (S.AWAITING_INFO, S.ACTIONED, S.CLOSED),
    S.AWAITING_INFO: (S.IN_REVIEW, S.ACTIONED, S.CLOSED),
    S.ACTIONED: (S.CLOSED, S.IN_REVIEW),
    S.CLOSED: (),
}
# Concern status each decision moves to. [J] revisit with the clinical reviewer.
ACTION_TARGET = {
    A.CLASSIFY: S.IN_REVIEW, A.CONFIRM: S.IN_REVIEW, A.OVERRIDE: S.IN_REVIEW,
    A.REQUEST_INFO: S.AWAITING_INFO, A.CALL: S.ACTIONED, A.ESCALATE: S.IN_REVIEW,
    A.ACKNOWLEDGE: S.IN_REVIEW, A.REFER: S.ACTIONED, A.CLOSE: S.CLOSED,
}


class IllegalTransition(Exception):
    pass


def _require_clinician(user, facility_id):
    profile = getattr(user, "provider_profile", None)
    if not (profile and profile.clinical_privileges):
        raise PermissionDenied("Only verified providers with clinical privileges can decide on concerns.")
    if not facility_ids_for(user, [Role.CLINICIAN]).filter(facility_id=facility_id).exists():
        raise PermissionDenied("Not a clinician at this concern's facility.")


@transaction.atomic
def record_decision(concern_id, provider, action, *, suggestion=None, final_category=None,
                    rationale="", call_session=None, consultation=None, occurred_at=None):
    """The only way a clinical decision is written. Sets first_response_at on the first PROVIDER decision."""
    concern = Concern.objects.select_for_update().get(pk=concern_id)
    _require_clinician(provider, concern.assigned_facility_id)
    action = A(action)
    if action == A.OVERRIDE and not rationale.strip():
        raise ValueError("An override needs a rationale.")
    if action in (A.CONFIRM, A.OVERRIDE) and suggestion is None:
        raise ValueError("Confirm/override must reference the suggestion.")
    if suggestion is not None and suggestion.concern_id != concern.id:
        raise ValueError("Suggestion belongs to a different concern.")

    target = ACTION_TARGET[action]
    if target != concern.status and target not in TRANSITIONS[concern.status]:
        raise IllegalTransition(f"{concern.status} -> {target} (action {action})")

    at = occurred_at or timezone.now()
    decision = ConcernDecision.objects.create(
        concern=concern, provider=provider, action=action, suggestion=suggestion,
        final_category=final_category, rationale=rationale, call_session=call_session,
        consultation=consultation, occurred_at=at,
    )
    concern.status = target
    if concern.first_response_at is None:
        concern.first_response_at = at
    if concern.assigned_to_id is None:
        concern.assigned_to = provider
    concern.save(update_fields=["status", "first_response_at", "assigned_to", "updated_at"])
    return decision


def record_provider_message(concern_id, message):
    """Call after a PROVIDER-sent outbound message to the mother. Automated messages (system sender,
    including the urgent safety instruction) never count: the target must not measure our own auto-reply."""
    if message.sender_kind != message.SenderKind.PROVIDER or message.direction != message.Direction.OUT:
        return False
    return bool(
        Concern.objects.filter(pk=concern_id, mother_id=message.conversation.mother_id,
                               first_response_at__isnull=True)
        .update(first_response_at=message.occurred_at)
    )