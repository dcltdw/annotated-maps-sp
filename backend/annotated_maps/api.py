from ninja import NinjaAPI

from core.api import router as core_router
from maps.api import router as maps_router

api = NinjaAPI(version="1.0.0", title="Annotated Maps API")
api.add_router("/", core_router)
api.add_router("/", maps_router)
