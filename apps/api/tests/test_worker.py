import uuid
from types import SimpleNamespace

import app.worker as worker_module
from app.models import RunStatus
from app.runner.protocol import ToolResult
from app.worker import Worker


class FakeSession:
    def __init__(self, run: SimpleNamespace) -> None:
        self.run = run
        self.commits = 0

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get(self, _model: object, _identifier: object) -> SimpleNamespace:
        return self.run

    def commit(self) -> None:
        self.commits += 1


def test_hidden_check_publishes_started_and_completed_events(monkeypatch) -> None:
    run = SimpleNamespace(status=RunStatus.running, stage="Candidate investigation")
    session = FakeSession(run)
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(worker_module, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        worker_module,
        "append_event",
        lambda _session, _run_id, kind, payload: events.append((kind, payload)),
    )
    expected = ToolResult(
        call_id="hidden-static",
        name="static",
        status="ok",
        output="passed",
    )

    result = Worker().hidden_check(
        uuid.uuid4(),
        "static",
        lambda: expected,
    )

    assert result is expected
    assert run.stage == "Hidden judge · static"
    assert [kind for kind, _ in events] == [
        "judge.check.started",
        "judge.check.completed",
    ]
    assert events[-1][1]["check"] == "static"
    assert events[-1][1]["status"] == "ok"
    assert int(events[-1][1]["duration_ms"]) >= 0
