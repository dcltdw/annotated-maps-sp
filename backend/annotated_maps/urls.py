from django.urls import include, path

from annotated_maps.api import api

urlpatterns = [
    path("api/v1/", api.urls),
    # Cluster-internal scrape target. Mounted at root ON PURPOSE: the public
    # Ingress routes only /api here, so no public route reaches it (M2 §4).
    path("", include("django_prometheus.urls")),
]
