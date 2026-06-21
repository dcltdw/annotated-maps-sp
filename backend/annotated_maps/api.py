from ninja import NinjaAPI

from core.api import router as core_router
from core.auth_api import router as auth_router
from maps.api import router as maps_router
from maps.mod_api import router as mod_router

api = NinjaAPI(version="1.0.0", title="Annotated Maps API")
api.add_router("/", core_router)
api.add_router("/", maps_router)
api.add_router("/", mod_router)
api.add_router("/auth", auth_router)
