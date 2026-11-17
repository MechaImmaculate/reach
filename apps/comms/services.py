from django.db import transaction
from django.utils import timezone

from apps.consent.models import Purpose
from apps.consent.services import require_consent

from .models import Message, MessageDeliveryEvent

# Channels that need the mother's SMS consent. Voice and consultations are gated in their own services.
_CHANNEL_CONSENT = {Message.Channel.SMS: Purpose.SMS, Message.Channel.USSD: Purpose.SMS}


@transaction.atomic
def queue_outbound(conversation, body, *, channel, purpose=Message.Purpose.GENERAL,
                   sender_kind=Message.SenderKind.SYSTEM, sender_user=None, template=None,
                   in_reply_to=None, language="", idempotency_key=None):
    """Create an outbound message in 'queued'. Never marks anything sent: only a provider
    callback can move it past 'submitted'. Dispatch to the gateway is a worker's job (next step)."""
    if idempotency_key:
        existing = Message.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing
    needed = _CHANNEL_CONSENT.get(channel)
    if needed:
        require_consent(conversation.mother_id, needed)  # strict: no exemption, see open question
    now = timezone.now()
    msg = Message.objects.create(
        conversation=conversation, direction=Message.Direction.OUT, channel=channel,
        sender_kind=sender_kind, sender_user=sender_user, purpose=purpose, body=body,
        language=language, template=template, in_reply_to=in_reply_to,
        idempotency_key=idempotency_key, latest_status=Message.Status.QUEUED,
        latest_status_at=now, occurred_at=now,
    )
    MessageDeliveryEvent.objects.create(message=msg, status=Message.Status.QUEUED, occurred_at=now)
    return msg


@transaction.atomic
def apply_delivery_event(message_id, status, occurred_at, *, provider_status_raw="",
                         error_code="", webhook_event=None):
    """Always record the event (history is complete). Advance latest_status only to a strictly higher
    rank, so a late 'sent' can never overwrite 'delivered'. Returns (event, advanced)."""
    if status not in Message.STATUS_RANK:
        raise ValueError(f"Unknown delivery status: {status!r}")
    msg = Message.objects.select_for_update().get(pk=message_id)
    event = MessageDeliveryEvent.objects.create(
        message=msg, status=status, occurred_at=occurred_at,
        provider_status_raw=provider_status_raw, error_code=error_code, webhook_event=webhook_event,
    )
    advanced = Message.STATUS_RANK[status] > Message.STATUS_RANK[msg.latest_status]
    if advanced:
        msg.latest_status, msg.latest_status_at = status, occurred_at
        msg.save(update_fields=["latest_status", "latest_status_at"])
    return event, advanced