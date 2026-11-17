from django.contrib.gis.db import models as gis
from django.db import models
from django.db.models import Q

from apps.core.models import AppendOnlyModel, TimeStampedModel, UUIDModel


class MotherLocation(AppendOnlyModel):
    """What dashboards and analysis see: admin area + a grid-snapped point (~500 m).
    A new row per change; current = latest. Exact coordinates are NOT here (D-07)."""

    class Precision(models.TextChoices):
        COUNTY = "county"
        SUBCOUNTY = "subcounty"
        WARD = "ward"
        COMMUNITY = "community"
        GRID = "grid"

    class Source(models.TextChoices):
        MOTHER_REPORTED = "mother_reported"
        CHW = "chw"
        FACILITY = "facility"

    mother = models.ForeignKey("mothers.Mother", on_delete=models.PROTECT, related_name="locations")
    precision = models.CharField(max_length=10, choices=Precision)
    admin_area = models.ForeignKey("geo.AdminArea", on_delete=models.PROTECT, related_name="mother_locations")
    grid_point = gis.PointField(geography=True, srid=4326, null=True, blank=True)
    source = models.CharField(max_length=16, choices=Source)
    collected_by = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    purpose = models.CharField(max_length=100)
    consent_record = models.ForeignKey("consent.ConsentRecord", on_delete=models.PROTECT, related_name="+")
    occurred_at = models.DateTimeField()

    class Meta(AppendOnlyModel.Meta):
        constraints = [
            models.CheckConstraint(
                condition=Q(precision="grid", grid_point__isnull=False) | ~Q(precision="grid"),
                name="motherlocation_grid_needs_point",
            ),
        ]
        indexes = [models.Index(fields=["mother", "-occurred_at"], name="motherlocation_latest_idx")]


class MotherExactLocation(AppendOnlyModel):
    """Restricted. Readable only through a SECURITY DEFINER function that writes an AccessLog row;
    the app role has no direct SELECT. Collected only when a purpose (e.g. a home visit) justifies it."""

    mother = models.ForeignKey("mothers.Mother", on_delete=models.PROTECT, related_name="exact_locations")
    point = gis.PointField(geography=True, srid=4326, spatial_index=False)
    purpose = models.CharField(max_length=100)
    consent_record = models.ForeignKey("consent.ConsentRecord", on_delete=models.PROTECT, related_name="+")
    collected_by = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    occurred_at = models.DateTimeField()

    class Meta(AppendOnlyModel.Meta):
        indexes = [models.Index(fields=["mother", "-occurred_at"], name="exactlocation_latest_idx")]


class CatchmentArea(TimeStampedModel):
    """A facility's area for a stated purpose and method. Nearest is not always appropriate:
    a referral destination must satisfy the clinical service requirement first."""

    class Kind(models.TextChoices):
        ADMIN = "admin"
        SERVICE_AREA = "service_area"
        ISOCHRONE = "isochrone"

    facility = models.ForeignKey("facilities.Facility", on_delete=models.CASCADE, related_name="catchments")
    kind = models.CharField(max_length=14, choices=Kind)
    travel_mode = models.CharField(max_length=20, blank=True)
    threshold_minutes = models.PositiveIntegerField(null=True, blank=True)
    geom = gis.MultiPolygonField(srid=4326)
    assumptions = models.JSONField(default=dict, blank=True)
    dataset = models.ForeignKey("geo.GeoDatasetVersion", on_delete=models.PROTECT, related_name="catchments")
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)


class AccessibilityResult(UUIDModel):
    """Calculated, never observed. `is_estimate` is always true and the UI must say so."""

    class Method(models.TextChoices):
        STRAIGHT_LINE = "straight_line"
        ROAD_NETWORK = "road_network"

    origin_area = models.ForeignKey("geo.AdminArea", on_delete=models.CASCADE, related_name="accessibility_results")
    facility = models.ForeignKey("facilities.Facility", on_delete=models.CASCADE, related_name="accessibility_results")
    method = models.CharField(max_length=14, choices=Method)
    distance_m = models.PositiveIntegerField()
    travel_seconds = models.PositiveIntegerField(null=True, blank=True)
    is_estimate = models.BooleanField(default=True)
    dataset = models.ForeignKey("geo.GeoDatasetVersion", on_delete=models.PROTECT, related_name="accessibility_results")
    computed_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["origin_area", "facility", "method", "dataset"], name="accessibility_unique_run"
            ),
            models.CheckConstraint(condition=Q(is_estimate=True), name="accessibility_always_estimate"),
            models.CheckConstraint(
                condition=Q(method="straight_line") | Q(travel_seconds__isnull=False),
                name="accessibility_road_needs_time",
            ),
        ]
