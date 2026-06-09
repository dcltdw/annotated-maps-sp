from django.conf import settings
from ninja import Router

router = Router()


@router.get("/health")
def health(request):
    return {
        "status": "ok",
        "version": settings.API_VERSION,  # type: ignore[misc]  # custom setting not in django-stubs
        "git_sha": settings.GIT_SHA,  # type: ignore[misc]  # custom setting not in django-stubs
    }
