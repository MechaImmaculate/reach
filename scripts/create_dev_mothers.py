"""DEV ONLY. Run AFTER create_dev_users.py. Creates two synthetic mothers with web accounts, one
pregnant and one postnatal with a baby, plus open appointment slots for dev-clinician.
Run:  python manage.py shell -c "exec(open('scripts/create_dev_mothers.py').read())"
Sign in at /mother/signin/ with 0700000001 or 0700000002. The code prints in the runserver terminal
(simulated, no SMS is sent). Not the Nairobi seed."""
from datetime import date, time, timedelta

from django.conf import settings
from django.utils import timezone

assert settings.DEBUG, "dev fixture refuses to run with DEBUG off"
from apps.accounts.models import User
from apps.appointments.services import create_slots
from apps.care.models import Newborn, PregnancyEpisode
from apps.core.fields import blind_index, normalise_msisdn
from apps.core.ids import short_code
from apps.facilities.models import Facility
from apps.mothers.models import Mother, MotherAccount, MotherContact, MotherFacilityAccess

now, today = timezone.now(), timezone.localdate()
fac = Facility.objects.get(name="DEV Health Centre (synthetic)")
clin = User.objects.get(email="dev-clinician@reach.test")

def make(name, phone, dob, episode_kw, baby_days=None):
    msisdn = normalise_msisdn(phone)
    if MotherContact.objects.filter(value_hash=blind_index(msisdn)).exists():
        return print("exists:", name)
    m = Mother.objects.create(short_code=short_code("M"), full_name=name, date_of_birth=dob, registered_facility=fac,
                              registered_by=clin, is_synthetic=True, preferred_channel="web")
    MotherContact.objects.create(mother=m, kind="primary_phone", value=msisdn, value_hash=blind_index(msisdn), is_primary=True)
    MotherFacilityAccess.objects.create(mother=m, facility=fac, kind="primary", granted_by=clin, reason="dev fixture")
    ep = PregnancyEpisode.objects.create(mother=m, facility=fac, responsible_provider=clin, registered_at=now, **episode_kw)
    if baby_days is not None:
        Newborn.objects.create(episode=ep, birth_date=today - timedelta(days=baby_days), sex="female", registered_by=clin)
    MotherAccount.objects.create(mother=m, enabled_by=clin)
    print("created:", name, phone)

make("Amina Test (synthetic)", "0700000001", date(1996, 4, 2),
     dict(status="active", lmp_date=today - timedelta(weeks=24), edd_date=today + timedelta(weeks=16)))
make("Wanjiru Test (synthetic)", "0700000002", date(1993, 9, 20),
     dict(status="postnatal", edd_date=today - timedelta(days=12)), baby_days=12)

for d in (1, 2, 3):
    day = today + timedelta(days=d)
    try:
        n = create_slots(clin, fac, day, time(9, 0), time(12, 0), 30)
        print(f"{day}: {n} new slots")
    except ValueError as e:
        print(day, e)
print("OK. Mother sign-in: /mother/signin/ with 0700000001 or 0700000002 (code shows in this terminal).")
