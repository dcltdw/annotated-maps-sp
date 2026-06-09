from django.urls import path

from annotated_maps.api import api

urlpatterns = [path("api/v1/", api.urls)]
