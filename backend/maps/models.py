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
    title = models.CharField(max_length=200, blank=True)
    point = gis.PointField(null=True, blank=True)

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

    class Meta:
        ordering = ["order"]

    def __str__(self) -> str:
        return f"{self.rule_type} section of note {self.note_id}"
