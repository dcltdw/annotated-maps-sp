from ninja import NinjaAPI

from core.api import router as core_router

api = NinjaAPI(version="1.0.0", title="Annotated Maps API")
api.add_router("/", core_router)
