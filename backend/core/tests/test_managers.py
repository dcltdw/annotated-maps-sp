from core.models import Group


def test_tenant_scoped_subclass_default_manager_is_soft_delete():
    # Regression: TenantScopedModel.Meta must inherit BaseModel.Meta so its
    # subclasses (Group, and the maps app's Map/Note) keep SoftDeleteManager as
    # the DEFAULT manager. Otherwise soft-deleted rows leak through default
    # queries, related lookups, and the notes API.
    assert type(Group._default_manager).__name__ == "SoftDeleteManager"
    assert type(Group._base_manager).__name__ == "Manager"
