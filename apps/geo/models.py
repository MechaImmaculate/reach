from django.contrib.gis.db import models as gis
from django.db import models
from django.db.models import Q

from apps.core.models import UUIDModel


class GeoDatasetVersion(UUIDModel):
    """Provenance for every boundary / road / facility dataset (SRS FR-138)."""

    name = models.CharField(max_length=200)
    publisher = models.CharField(max_length=200, blank=True)
    licence = models.CharField(max_length=200, blank=True)
    source_url = models.URLField(blank=True)
    version_label = models.CharField(max_length=100, blank=True)
    retrieved_at = models.DateTimeField()
    checksum_sha256 = models.CharField(max_length=64, blank=True)
    verified = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.name} {self.version_label}".strip()


class AdminArea(UUIDModel):
    class Level(models.TextChoices):
        COUNTRY = "country"
        COUNTY = "county"
        SUBCOUNTY = "subcounty"
        WARD = "ward"
        COMMUNITY = "community"

    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    level = models.CharField(max_length=10, choices=Level)
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50)
    geom = gis.MultiPolygonField(srid=4326, null=True, blank=True)
    dataset = models.ForeignKey(GeoDatasetVersion, on_delete=models.PROTECT, related_name="areas")
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["level", "code"], name="adminarea_unique_level_code"),
            models.CheckConstraint(
                condition=Q(level="country") | Q(parent__isnull=False),
                name="adminarea_parent_required_below_country",
            ),
        ]
        indexes = [models.Index(fields=["level", "name"], name="adminarea_level_name_idx")]

    def __str__(self):
        return f"{self.name} ({self.level})"
