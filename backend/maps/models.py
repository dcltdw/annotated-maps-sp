from django.contrib.gis.db import models as gis
from django.db import models

from core.models import BaseModel, TenantScopedModel, User


class Map(TenantScopedModel):
    name = models.CharField(max_length=200)
    center = gis.PointField()
    default_zoom = models.PositiveSmallIntegerField(default=12)

    def __str__(self) -> str:
        return self.name


class Note(TenantScopedModel):
    map = models.ForeignKey(Map, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notes")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="appends"
    )
    title = models.CharField(max_length=200, blank=True)
    point = gis.PointField(null=True, blank=True)
    # A note is anchored to exactly one of point / area / path (enforced in the write API).
    area = gis.PolygonField(null=True, blank=True)  # freehand polygons AND circles (N-gon)
    path = gis.LineStringField(null=True, blank=True)  # routes / boundary lines

    # --- Sandbox/demo metadata (only meaningful when settings.SANDBOX_MODE) ---
    is_seed = models.BooleanField(default=False)  # True only for seed content (permanent)
    session_key = models.CharField(max_length=40, blank=True, default="")  # ephemeral session
    created_ip = models.GenericIPAddressField(null=True, blank=True)  # ephemeral creator IP

    def __str__(self) -> str:
        return self.title or f"Note {self.id}"


class Section(BaseModel):
    class RuleType(models.TextChoices):
        PUBLIC = "public"
        AUDIENCE = "audience"
        ATTRIBUTE_GATE = "attribute_gate"
        PRIVATE = "private"

    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="sections")
    order = models.PositiveSmallIntegerField(default=0)
    content = models.TextField()
    rule_type = models.CharField(max_length=20, choices=RuleType.choices)
    rule_params = models.JSONField(default=dict, blank=True)
    teaser = models.BooleanField(default=False)
    teaser_text = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["order"]

    def __str__(self) -> str:
        return f"{self.rule_type} section of note {self.note_id}"
