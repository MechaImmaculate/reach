from .models import ConsentRecord


class ConsentRequired(Exception):
    def __init__(self, mother_id, purpose):
        super().__init__(f"No granted consent for purpose '{purpose}' (mother {mother_id})")
        self.mother_id, self.purpose = mother_id, purpose


def current_status(mother, purpose):
    """Latest consent status for (mother, purpose), or None if never recorded. Same rule as the
    consent_current view: latest occurred_at wins, id breaks ties (UUIDv7 is time-ordered)."""
    mother_id = getattr(mother, "pk", mother)
    return (
        ConsentRecord.objects.filter(mother_id=mother_id, purpose=purpose)
        .order_by("-occurred_at", "-id")
        .values_list("status", flat=True)
        .first()
    )


def has_consent(mother, purpose) -> bool:
    return current_status(mother, purpose) == ConsentRecord.Status.GRANTED


def require_consent(mother, purpose):
    if not has_consent(mother, purpose):
        raise ConsentRequired(getattr(mother, "pk", mother), purpose)