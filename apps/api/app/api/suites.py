from fastapi import APIRouter, Depends

from app.config import get_settings
from app.models import UserAccount
from app.scenario.suite import BenchmarkSuite, load_suites
from app.security import current_user

router = APIRouter(prefix="/suites", tags=["suites"])


@router.get("", response_model=list[BenchmarkSuite])
def list_suites(
    _: UserAccount = Depends(current_user),
) -> list[BenchmarkSuite]:
    settings = get_settings()
    return load_suites(settings.suites_root, settings.scenarios_root)
