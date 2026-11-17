from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.fields import EncryptedTextField
from apps.core.models import TimeStampedModel


class MotherQuerySet(models.QuerySet):
    def visible_to(self, user):
        """The ONLY sanctioned way to list mothers for a user.

        Visible if (a) the user holds a mother-visible role at a facility with an active access
        grant for her, or (b) the user is her currently assigned CHW. County and system admins
        see nothing here. Relations are referenced by name (`chw_assignments`) so this module
        does not import `chw`.
        """
        from apps.facilities.access import mother_visible_facility_ids

        if not getattr(user, "is_authenticated", False):
            return self.none()
        now = timezone.now()
        via_facility = (
            Q(access_grants__facility_id__in=mother_visible_facility_ids(user))
            & Q(access_grants__valid_from__lte=now)
            & (Q(access_grants__valid_to__isnull=True) | Q(access_grants__valid_to__gt=now))
        )
        via_chw = (
            Q(chw_assignments__chw=user)
            & Q(chw_assignments__valid_from__lte=now)
            & (Q(chw_assignments__valid_to__isnull=True) | Q(chw_assignments__valid_to__gt=now))
        )
        return self.filter(merged_into__isnull=True).filter(via_facility | via_chw).distinct()


class Mother(TimeStampedModel):
    """One longitudinal identity. Pregnancies are `care.PregnancyEpisode` rows, never columns here."""

    class Language(models.TextChoices):
        ENGLISH = "en"
        KISWAHILI = "sw"

    class Channel(models.TextChoices):
        SMS = "sms"
        VOICE = "voice"
        WEB = "web"

    class RegisteredVia(models.TextChoices):
        FACILITY = "facility"
        CHW = "chw"
        SELF = "self"

    class Status(models.TextChoices):
        ACTIVE = "active"
        INACTIVE = "inactive"
        TRANSFERRED = "transferred"

    short_code = models.CharField(max_length=12, unique=True)
    full_name = EncryptedTextField()
    date_of_birth = models.DateField(null=True, blank=True)
    age_estimate = models.PositiveSmallIntegerField(null=True, blank=True)
    preferred_language = models.CharField(max_length=2, choices=Language, default=Language.ENGLISH)
    preferred_channel = models.CharField(max_length=5, choices=Channel, default=Channel.SMS)
    registered_facility = models.ForeignKey("facilities.Facility", on_delete=models.PROTECT, related_name="registered_mothers")
    registered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    registered_via = models.CharField(max_length=10, choices=RegisteredVia, default=RegisteredVia.FACILITY)
    status = models.CharField(max_length=12, choices=Status, default=Status.ACTIVE)
    dedupe_key = models.CharField(max_length=64, db_index=True, blank=True)  # HMAC(normalised name + DOB)
    merged_into = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="merged_from")
    is_synthetic = models.BooleanField(default=False)

    objects = MotherQuerySet.as_manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(date_of_birth__isnull=False) | Q(age_estimate__isnull=False),
                name="mother_age_or_dob_present",
            ),
            models.CheckConstraint(condition=~Q(merged_into=F("id")), name="mother_not_merged_into_self"),
        ]
        indexes = [models.Index(fields=["registered_facility", "status"], name="mother_facility_status_idx")]


class MotherContact(TimeStampedModel):
    """Phone numbers are NOT identity (shared phones, SIM changes). Lookup by blind index;
    an ambiguous match routes to a human, it never auto-picks a mother."""

    class Kind(models.TextChoices):
        PRIMARY_PHONE = "primary_phone"
        ALT_PHONE = "alt_phone"
        EMERGENCY_CONTACT = "emergency_contact"

    mother = models.ForeignKey(Mother, on_delete=models.CASCADE, related_name="contacts")
    kind = models.CharField(max_length=20, choices=Kind)
    value = EncryptedTextField()  # normalised E.164
    value_hash = models.CharField(max_length=64, db_index=True)
    hash_key_version = models.PositiveSmallIntegerField(default=1)
    contact_name = EncryptedTextField(blank=True, default="")  # for emergency contacts
    is_primary = models.BooleanField(default=False)
    is_shared_device = models.BooleanField(default=False)
    discreet_mode = models.BooleanField(default=False)  # no clinical content in SMS
    verified_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["mother"],
                condition=Q(kind="primary_phone", is_primary=True, active=True),
                name="mothercontact_one_active_primary_phone",
            ),
        ]


class MotherFacilityAccess(TimeStampedModel):
    """Which facilities may see a mother, and until when. A receiving facility gets a time-boxed
    grant when a referral is issued (data minimisation); revocation sets valid_to."""

    class Kind(models.TextChoices):
        PRIMARY = "primary"
        REFERRAL = "referral"
        CONSULTATION = "consultation"
        SHARED_CARE = "shared_care"

    mother = models.ForeignKey(Mother, on_delete=models.CASCADE, related_name="access_grants")
    facility = models.ForeignKey("facilities.Facility", on_delete=models.CASCADE, related_name="mother_access_grants")
    kind = models.CharField(max_length=15, choices=Kind)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    reason = models.CharField(max_length=300, blank=True)
    source_type = models.CharField(max_length=30, blank=True)  # e.g. "referral"
    source_ref = models.UUIDField(null=True, blank=True)  # id of that referral (no FK: avoids an app cycle)
    valid_from = models.DateTimeField(default=timezone.now)
    valid_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True) | Q(valid_to__gt=F("valid_from")),
                name="motherfacilityaccess_valid_range",
            ),
        ]
        indexes = [models.Index(fields=["facility", "mother"], name="mfa_facility_mother_idx")]
