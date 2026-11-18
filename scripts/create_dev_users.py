"""DEV ONLY. Creates one synthetic facility and a few users so you can see each workspace.
Run:  python manage.py shell -c "exec(open('scripts/create_dev_users.py').read())"
Password: env REACH_DEV_PASSWORD or the default below. Refuses to run when DEBUG is off.
This is NOT the Nairobi seed; it only creates what is needed to sign in."""
import os

from django.conf import settings
from django.utils import timezone

assert settings.DEBUG, "dev fixture refuses to run with DEBUG off"
from apps.accounts.models import ProviderProfile, User
from apps.facilities.models import Facility, Membership, Role
from apps.geo.models import AdminArea, GeoDatasetVersion

PASSWORD = os.environ.get("REACH_DEV_PASSWORD", "reach-dev-password-1")
now = timezone.now()
ds, _ = GeoDatasetVersion.objects.get_or_create(
    name="DEV synthetic boundaries", defaults=dict(retrieved_at=now, verified=False, notes="Placeholder, not real boundaries"))
country, _ = AdminArea.objects.get_or_create(level="country", code="KE", defaults=dict(name="Kenya (dev)", dataset=ds))
county, _ = AdminArea.objects.get_or_create(level="county", code="047", defaults=dict(name="Nairobi (dev)", parent=country, dataset=ds))
ward, _ = AdminArea.objects.get_or_create(level="ward", code="DEV-W1", defaults=dict(name="Dev Ward", parent=county, dataset=ds))
fac, _ = Facility.objects.get_or_create(name="DEV Health Centre (synthetic)", defaults=dict(
    facility_type="health_centre", kephl_level=3, ward=ward, status="active",
    is_synthetic=True, data_source="synthetic", accepts_referrals=True))
fac2, _ = Facility.objects.get_or_create(name="DEV Sub-county Hospital (synthetic)", defaults=dict(
    facility_type="subcounty_hospital", kephl_level=4, ward=ward, status="active",
    is_synthetic=True, data_source="synthetic", accepts_referrals=True))

people = [
    ("dev-clinician@reach.test", "Dev Clinician", [(Role.CLINICIAN, fac), (Role.CLINICIAN, fac2)]),
    ("dev-chw@reach.test", "Dev CHW", [(Role.CHW, fac)]),
    ("dev-facility@reach.test", "Dev Facility Admin", [(Role.FACILITY_ADMIN, fac)]),
    ("dev-county@reach.test", "Dev County Admin", [(Role.COUNTY_ADMIN, None)]),
    ("dev-multi@reach.test", "Dev Multi-role", [(Role.CLINICIAN, fac), (Role.FACILITY_ADMIN, fac)]),
]
for email, name, roles in people:
    user, created = User.objects.get_or_create(email=email, defaults=dict(full_name=name))
    if created:
        user.set_password(PASSWORD)
        user.save()
    for role, facility in roles:
        Membership.objects.get_or_create(user=user, facility=facility, role=role, defaults=dict(
            valid_from=now, admin_area=county if role == Role.COUNTY_ADMIN else None))
    if any(r == Role.CLINICIAN for r, _ in roles):
        ProviderProfile.objects.get_or_create(user=user, defaults=dict(
            cadre="nurse_midwife", verification_status="verified", verified_at=now, clinical_privileges=True))
print("OK. Sign in at /accounts/login/ as:", ", ".join(e for e, _, _ in people), "| password:", PASSWORD)
