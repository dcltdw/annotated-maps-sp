import uuid

from django.db import models
from django.utils import timezone

from core.managers import SoftDeleteManager


class BaseModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=0)
    deleted_at = models.DateTimeField(null=True, blank=True)

    all_objects = models.Manager()
    objects = SoftDeleteManager()

    class Meta:
        abstract = True
        default_manager_name = "objects"
        # base_manager_name = the UNFILTERED manager so related lookups / prefetch
        # still resolve soft-deleted parents (FK integrity). default_manager_name =
        # the SoftDeleteManager so normal queries / the API hide soft-deleted rows.
        # Subclasses must NOT override these to the plain manager (would leak deleted rows).
        base_manager_name = "all_objects"

    def save(self, *args, **kwargs):
        self.version += 1
        super().save(*args, **kwargs)

    def soft_delete(self):
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at", "version", "updated_at"])


class Tenant(BaseModel):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)

    def __str__(self) -> str:
        return self.name


class TenantScopedModel(BaseModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="+")

    class Meta(BaseModel.Meta):
        # Inherit BaseModel.Meta so default_manager_name/base_manager_name carry
        # over — otherwise scoped subclasses silently default to the UNFILTERED
        # manager (soft-deleted rows would leak through default queries / the API).
        abstract = True


class User(BaseModel):
    display_name = models.CharField(max_length=200)
    reputation = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return self.display_name


class Group(TenantScopedModel):
    name = models.CharField(max_length=200)
    members = models.ManyToManyField(User, related_name="groups", blank=True)

    def __str__(self) -> str:
        return self.name


class Membership(BaseModel):
    class Role(models.TextChoices):
        OWNER = "owner"
        CONTRIBUTOR = "contributor"
        VIEWER = "viewer"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=20, choices=Role.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "tenant"], name="unique_user_per_tenant"),
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.tenant} ({self.role})"


class AuditEvent(BaseModel):
    """Append-only log of security- and content-relevant events. Never updated or deleted."""

    tenant = models.ForeignKey(Tenant, null=True, on_delete=models.SET_NULL, related_name="+")
    actor_id = models.UUIDField(null=True, blank=True)
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=100, blank=True)
    target_id = models.UUIDField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        return f"{self.action}"
