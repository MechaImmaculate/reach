from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import AppendOnlyModel, TimeStampedModel, UUIDModel


class LabelledDataset(TimeStampedModel):
    """Training / validation / test data is governed separately from operational records (NFR-029)."""

    class Kind(models.TextChoices):
        SYNTHETIC = "synthetic"
        CLINICIAN_LABELLED = "clinician_labelled"

    class Split(models.TextChoices):
        TRAIN = "train"
        VALIDATION = "validation"
        TEST = "test"

    name = models.CharField(max_length=200)
    version = models.CharField(max_length=50)
    kind = models.CharField(max_length=20, choices=Kind)
    split = models.CharField(max_length=12, choices=Split)
    n_samples = models.PositiveIntegerField()
    languages = models.JSONField(default=list)
    labelling_protocol = models.TextField(blank=True)
    governance_ref = models.CharField(max_length=200, blank=True)  # authorisation / DPIA reference

    class Meta:
        constraints = [models.UniqueConstraint(fields=["name", "version", "split"], name="labelleddataset_unique")]


class ModelVersion(TimeStampedModel):
    class Status(models.TextChoices):
        SHADOW = "shadow"  # predictions logged, never shown to drive workflow
        LIMITED = "limited"
        APPROVED = "approved"
        REJECTED = "rejected"  # e.g. the earlier 6.4%-precision model, kept for the record
        RETIRED = "retired"

    name = models.CharField(max_length=100)
    version = models.CharField(max_length=50)
    task = models.CharField(max_length=60, default="message_classification")
    status = models.CharField(max_length=10, choices=Status, default=Status.SHADOW)
    artifact_sha256 = models.CharField(max_length=64, blank=True)
    training_dataset = models.ForeignKey(LabelledDataset, null=True, blank=True, on_delete=models.PROTECT, related_name="trained_models")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["name", "version"], name="modelversion_unique"),
            models.CheckConstraint(
                condition=~Q(status__in=["limited", "approved"]) | Q(approved_by__isnull=False, approved_at__isnull=False),
                name="modelversion_operational_needs_approval",
            ),
        ]


class ModelEvaluationRun(AppendOnlyModel):
    """Metrics include precision, recall, F1, confusion matrix and per-language breakdowns.
    Clinical thresholds are set with qualified reviewers, never by accuracy alone."""

    model_version = models.ForeignKey(ModelVersion, on_delete=models.PROTECT, related_name="evaluations")
    dataset = models.ForeignKey(LabelledDataset, on_delete=models.PROTECT, related_name="evaluations")
    n_samples = models.PositiveIntegerField()
    metrics = models.JSONField()
    thresholds_ref = models.CharField(max_length=200, blank=True)
    clinical_signoff_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    run_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    occurred_at = models.DateTimeField()
