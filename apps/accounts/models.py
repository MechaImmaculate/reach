from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel, UUIDModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("email is required")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra)


class User(UUIDModel, AbstractBaseUser, PermissionsMixin):
    """Staff, clinicians, CHWs and admins. Mothers are NOT staff users: they are `mothers.Mother`,
    with an optional separate `mothers.MotherAccount` for web sign-in (see docs/06-mother-access.md)."""

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)  # Django admin access only
    mfa_required = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]
    objects = UserManager()

    def __str__(self):
        return self.email


class ProviderProfile(TimeStampedModel):
    class Cadre(models.TextChoices):
        DOCTOR = "doctor"
        CLINICAL_OFFICER = "clinical_officer"
        NURSE_MIDWIFE = "nurse_midwife"
        NURSE = "nurse"
        CHW = "chw"
        OTHER = "other"

    class Verification(models.TextChoices):
        UNVERIFIED = "unverified"
        VERIFIED = "verified"
        SUSPENDED = "suspended"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="provider_profile")
    cadre = models.CharField(max_length=20, choices=Cadre)
    regulator = models.CharField(max_length=50, blank=True)  # e.g. the professional council
    registration_number = models.CharField(max_length=50, blank=True)
    verification_status = models.CharField(max_length=12, choices=Verification, default=Verification.UNVERIFIED)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    verified_at = models.DateTimeField(null=True, blank=True)
    clinical_privileges = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(clinical_privileges=False) | Q(verification_status="verified"),
                name="providerprofile_privileges_require_verification",
            ),
        ]
