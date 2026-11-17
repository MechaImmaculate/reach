import pgtrigger
from django.db import models
from django.db.models.functions import Now

from .ids import uuid7


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(UUIDModel):
    created_at = models.DateTimeField(db_default=Now(), editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AppendOnlyModel(UUIDModel):
    """Insert-only rows. Corrections are new rows.

    `occurred_at` (declared on each subclass) is when it really happened, per the provider
    or device. `recorded_at` is server time, set by the database, never by the client.

    Enforced by a Postgres trigger. Subclasses that declare their own Meta MUST inherit
    `AppendOnlyModel.Meta` or the trigger is lost:

        class Meta(AppendOnlyModel.Meta):
            indexes = [...]
    """

    recorded_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        abstract = True
        triggers = [
            pgtrigger.Protect(
                name="append_only",
                operation=pgtrigger.Update | pgtrigger.Delete,
            )
        ]
