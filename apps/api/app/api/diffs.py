import re
import tarfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_session
from app.models import BenchmarkRun, UserAccount
from app.security import can_access_run, current_user

router = APIRouter(prefix="/runs", tags=["diffs"])
settings = get_settings()

_DIFF_FILE = re.compile(r"^diff --git ")


def _archive_candidates(run_id: uuid.UUID) -> list[Path]:
    root = Path(settings.artifact_root)
    return [
        root / f"{run_id}.tar.gz",
        root / f"{run_id}-failure-checkpoint.tar.gz",
    ]


def _stats(diff_text: str) -> dict[str, int]:
    added = removed = 0
    files = 0
    for line in diff_text.splitlines():
        if _DIFF_FILE.match(line):
            files += 1
        elif line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return {"added_lines": added, "removed_lines": removed, "file_count": files}


def _read_members(tar_path: Path) -> list[dict[str, str]]:
    repos: dict[str, dict[str, str]] = {}
    with tarfile.open(tar_path, "r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            path = member.name
            if not path.startswith("artifacts/") or not (path.endswith(".diff") or path.endswith(".status")):
                continue
            repo = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            entry = repos.setdefault(repo, {})
            entry["status_text" if path.endswith(".status") else "diff_text"] = (
                archive.extractfile(member).read().decode("utf-8", errors="replace")
            )
    return [
        {
            "repo": repo,
            "diff_text": data.get("diff_text", ""),
            "status_text": data.get("status_text", ""),
        }
        for repo, data in sorted(repos.items())
    ]


@router.get("/{run_id}/diffs")
def run_diffs(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(current_user),
) -> list[dict[str, object]]:
    run = session.get(BenchmarkRun, run_id)
    if not can_access_run(session, user, run):
        raise HTTPException(status_code=404, detail="Run not found")
    for candidate in _archive_candidates(run_id):
        if candidate.exists():
            return [{**entry, **_stats(entry["diff_text"])} for entry in _read_members(candidate)]
    raise HTTPException(status_code=404, detail="No run archive available")
