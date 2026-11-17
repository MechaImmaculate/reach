from django.conf import settings
from django.contrib.gis.db import models as gis
from django.db import models
from django.db.models import F, Q

from apps.core.models import AppendOnlyModel, TimeStampedModel, UUIDModel


class Role(models.TextChoices):
    CLINICIAN = "clinician"
    CHW = "chw"
    FACILITY_ADMIN = "facility_admin"
    REFERRAL_COORDINATOR = "referral_coordinator"
    COUNTY_ADMIN = "county_admin"
    SYSTEM_ADMIN = "system_admin"


# Roles that may see mother identity at a facility. CHWs are scoped by CHWAssignment instead.
# County and system admins deliberately have NO clinical visibility.
MOTHER_VISIBLE_ROLES = {Role.CLINICIAN, Role.REFERRAL_COORDINATOR, Role.FACILITY_ADMIN}


class Facility(TimeStampedModel):
    class Type(models.TextChoices):
        DISPENSARY = "dispensary"
        HEALTH_CENTRE = "health_centre"
        SUBCOUNTY_HOSPITAL = "subcounty_hospital"
        COUNTY_REFERRAL = "county_referral"
        NATIONAL_REFERRAL = "national_referral"
        PRIVATE_CLINIC = "private_clinic"
        MATERNITY_HOME = "maternity_home"
        OTHER = "other"

    class Status(models.TextChoices):
        ACTIVE = "active"
        INACTIVE = "inactive"
        UNVERIFIED = "unverified"

    class Source(models.TextChoices):
        KMHFL = "kmhfl"
        MANUAL = "manual"
        SYNTHETIC = "synthetic"

    mfl_code = models.CharField(max_length=20, unique=True, null=True, blank=True)  # Kenya Master Facility List
    name = models.CharField(max_length=250)
    facility_type = models.CharField(max_length=20, choices=Type)
    kephl_level = models.PositiveSmallIntegerField(null=True, blank=True)  # 2..6
    ward = models.ForeignKey("geo.AdminArea", on_delete=models.PROTECT, related_name="facilities")
    location = gis.PointField(geography=True, srid=4326, null=True, blank=True)
    address_text = models.CharField(max_length=300, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    status = models.CharField(max_length=12, choices=Status, default=Status.UNVERIFIED)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    operating_hours = models.JSONField(default=dict, blank=True)
    accepts_referrals = models.BooleanField(default=False)
    data_source = models.CharField(max_length=10, choices=Source, default=Source.MANUAL)
    is_synthetic = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(kephl_level__isnull=True) | Q(kephl_level__gte=1, kephl_level__lte=6),
                name="facility_kephl_level_range",
            ),
        ]
        indexes = [models.Index(fields=["status", "facility_type"], name="facility_status_type_idx")]

    def __str__(self):
        return self.name


class Service(UUIDModel):
    class Category(models.TextChoices):
        ANTENATAL = "antenatal"
        POSTNATAL = "postnatal"
        DELIVERY = "delivery"
        EMERGENCY_OBSTETRIC = "emergency_obstetric"
        NEWBORN = "newborn"
        DIAGNOSTICS = "diagnostics"
        SPECIALIST = "specialist"
        OTHER = "other"

    code = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=Category)

    def __str__(self):
        return self.name


class FacilityService(TimeStampedModel):
    """Current state of one service at one facility. History lives in FacilityServiceVerification.
    Never infer a service from facility type (SRS 7.2)."""

    class Status(models.TextChoices):
        AVAILABLE = "available"
        LIMITED = "limited"
        UNAVAILABLE = "unavailable"
        UNKNOWN = "unknown"

    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name="services")
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="facility_services")
    status = models.CharField(max_length=12, choices=Status, default=Status.UNKNOWN)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    hours = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["facility", "service"], name="facilityservice_unique_pair")]


class FacilityServiceVerification(AppendOnlyModel):
    class Method(models.TextChoices):
        PHONE_CALL = "phone_call"
        SITE_VISIT = "site_visit"
        KMHFL_IMPORT = "kmhfl_import"
        COUNTY_REGISTER = "county_register"
        SYNTHETIC = "synthetic"

    facility_service = models.ForeignKey(FacilityService, on_delete=models.PROTECT, related_name="verifications")
    status = models.CharField(max_length=12, choices=FacilityService.Status)
    method = models.CharField(max_length=20, choices=Method)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    evidence_note = models.TextField(blank=True)
    occurred_at = models.DateTimeField()

    class Meta(AppendOnlyModel.Meta):
        indexes = [models.Index(fields=["facility_service", "-occurred_at"], name="fsverification_latest_idx")]


class FacilityPolicy(AppendOnlyModel):
    """Per-facility operating policy. The four-hour figure is a PROPOSED pilot target, agreed
    per facility with its own hours and exclusions. A change is a new row."""

    facility = models.ForeignKey(Facility, on_delete=models.PROTECT, related_name="policies")
    response_target_minutes = models.PositiveIntegerField(default=240)
    escalate_after_minutes = models.PositiveIntegerField(default=120)
    business_hours = models.JSONField(default=dict, blank=True)
    exclusions = models.TextField(blank=True)
    agreed_reference = models.CharField(max_length=200, blank=True)
    effective_from = models.DateTimeField()
    occurred_at = models.DateTimeField()

    class Meta(AppendOnlyModel.Meta):
        constraints = [
            models.CheckConstraint(
                condition=Q(escalate_after_minutes__lte=F("response_target_minutes")),
                name="facilitypolicy_escalate_before_target",
            ),
        ]
        indexes = [models.Index(fields=["facility", "-effective_from"], name="facilitypolicy_latest_idx")]


class ReferralArrangement(TimeStampedModel):
    class Channel(models.TextChoices):
        SMS = "sms"
        PHONE = "phone"
        EMAIL = "email"
        PORTAL = "portal"

    from_facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name="outgoing_arrangements")
    to_facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name="incoming_arrangements")
    channel = models.CharField(max_length=10, choices=Channel)
    contact_name = models.CharField(max_length=200, blank=True)
    contact_value = models.CharField(max_length=200, blank=True)
    active = models.BooleanField(default=True)
    agreed_at = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["from_facility", "to_facility"], name="arrangement_unique_pair"),
            models.CheckConstraint(condition=~Q(from_facility=F("to_facility")), name="arrangement_distinct_facilities"),
        ]


class Membership(TimeStampedModel):
    """user x facility x role. Lives here (not in accounts) to keep the app graph acyclic."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    facility = models.ForeignKey(Facility, null=True, blank=True, on_delete=models.CASCADE, related_name="memberships")
    admin_area = models.ForeignKey("geo.AdminArea", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    role = models.CharField(max_length=24, choices=Role)
    is_active = models.BooleanField(default=True)
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "facility", "role"],
                nulls_distinct=False,
                name="membership_unique_user_facility_role",
            ),
            models.CheckConstraint(
                condition=(
                    Q(role__in=["county_admin", "system_admin"])
                    | Q(facility__isnull=False)
                ),
                name="membership_facility_required_for_facility_roles",
            ),
            models.CheckConstraint(
                condition=~Q(role="county_admin") | Q(admin_area__isnull=False),
                name="membership_county_admin_needs_area",
            ),
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True) | Q(valid_to__gt=F("valid_from")),
                name="membership_valid_range",
            ),
        ]
        indexes = [models.Index(fields=["user", "is_active"], name="membership_user_active_idx")]
