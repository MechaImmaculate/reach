"""Mother sign-in: one-time codes over a phone number she already has on file.

Rules (docs/06-mother-access.md): no enumeration, no code to shared or ambiguous numbers,
codes are hashed, expire, and are attempt- and rate-limited. Nothing here claims an SMS was sent
unless a real backend delivered it.
"""
import hmac
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.core.fields import blind_index, normalise_msisdn

from .models import MotherAccount, MotherContact, MotherLoginCode

log = logging.getLogger("reach.mother_auth")

SESSION_KEY = "reach_mother_id"
CODE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
MAX_CODES_PER_HOUR = 3
SESSION_SECONDS = 2 * 60 * 60


class OtpDeliveryUnavailable(Exception):
    """No SMS gateway is connected (and we are not in DEBUG)."""


def clean_phone(raw: str) -> str:
    """Returns E.164 or raises ValueError."""
    return normalise_msisdn(raw)


def find_account(msisdn: str):
    """The one eligible account for this number, or None (unknown, ambiguous or shared device)."""
    contacts = (MotherContact.objects
                .filter(value_hash=blind_index(msisdn), active=True, is_shared_device=False,
                        kind__in=[MotherContact.Kind.PRIMARY_PHONE, MotherContact.Kind.ALT_PHONE],
                        mother__merged_into__isnull=True, mother__status="active",
                        mother__account__status__in=[MotherAccount.Status.INVITED, MotherAccount.Status.ACTIVE])
                .select_related("mother__account"))
    accounts = {c.mother.account.pk: c.mother.account for c in contacts}
    return next(iter(accounts.values())) if len(accounts) == 1 else None


def _hash(account, code: str) -> str:
    return blind_index(f"mother-otp:{account.pk}:{code}")


def _deliver(msisdn: str, code: str):
    backend = getattr(settings, "REACH_OTP_BACKEND", "console" if settings.DEBUG else "none")
    if backend == "console" and settings.DEBUG:
        print(f"\n[REACH DEV] sign-in code for {msisdn[:-3]}***: {code}  (simulated, no SMS was sent)\n")
        return
    raise OtpDeliveryUnavailable


def _audit(action, *, account=None, mother=None, msisdn="", ip=None):
    from apps.audit.models import AuditLog
    AuditLog.objects.create(
        action=action, mother=mother or (account.mother if account else None),
        object_type="mothers.motheraccount" if account else "mothers.login_attempt",
        object_id=str(account.pk) if account else (blind_index(msisdn)[:32] if msisdn else "none"),
        ip=ip, occurred_at=timezone.now())


def request_code(msisdn: str, ip=None) -> None:
    """Silent for unknown numbers. Raises OtpDeliveryUnavailable only when delivery itself is unavailable."""
    account = find_account(msisdn)
    if account is None:
        _audit("login_failed", msisdn=msisdn, ip=ip)
        _deliver_check()
        return
    now = timezone.now()
    if account.login_codes.filter(created_at__gte=now - timedelta(hours=1)).count() >= MAX_CODES_PER_HOUR:
        log.info("mother otp rate limit hit for account %s", account.pk)
        return
    code = f"{secrets.randbelow(10**6):06d}"
    MotherLoginCode.objects.create(account=account, code_hash=_hash(account, code), expires_at=now + CODE_TTL, ip=ip)
    _deliver(msisdn, code)


def _deliver_check():
    """Unknown numbers must look the same as known ones, including when delivery is unavailable."""
    backend = getattr(settings, "REACH_OTP_BACKEND", "console" if settings.DEBUG else "none")
    if not (backend == "console" and settings.DEBUG):
        raise OtpDeliveryUnavailable


def verify_code(msisdn: str, code: str, ip=None):
    """Returns the MotherAccount on success, else None (no reason given)."""
    account = find_account(msisdn)
    code = (code or "").strip()
    if account is None or not (code.isdigit() and len(code) == 6):
        _audit("login_failed", account=account, msisdn=msisdn, ip=ip)
        return None
    now = timezone.now()
    with transaction.atomic():
        row = (MotherLoginCode.objects.select_for_update()
               .filter(account=account, consumed_at__isnull=True, expires_at__gt=now)
               .order_by("-created_at").first())
        if row is None or row.attempts >= MAX_ATTEMPTS:
            ok = False
        else:
            MotherLoginCode.objects.filter(pk=row.pk).update(attempts=F("attempts") + 1)
            ok = hmac.compare_digest(row.code_hash, _hash(account, code))
        if ok:
            row.consumed_at = now
            row.save(update_fields=["consumed_at"])
            update = {"last_login_at": now}
            if account.status == MotherAccount.Status.INVITED:
                update.update(status=MotherAccount.Status.ACTIVE, activated_at=now)
            MotherAccount.objects.filter(pk=account.pk).update(**update)
            (MotherContact.objects.filter(mother=account.mother, value_hash=blind_index(msisdn), verified_at__isnull=True)
             .update(verified_at=now))
    if not ok:
        _audit("login_failed", account=account, msisdn=msisdn, ip=ip)
        return None
    _audit("login", account=account, ip=ip)
    account.refresh_from_db()
    return account


def start_session(request, account):
    """Flush first: a mother session and a staff session must never share a browser session."""
    request.session.flush()
    request.session[SESSION_KEY] = str(account.pk)
    request.session.set_expiry(SESSION_SECONDS)


def end_session(request):
    request.session.flush()
