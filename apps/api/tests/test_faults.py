from pathlib import Path

from app.runner.faults import FaultController
from app.runner.protocol import ToolCall, ToolResult


def test_scripted_failure_then_passthrough(tmp_path: Path) -> None:
    script = tmp_path / "fault.yaml"
    script.write_text(
        """
version: 1
rules:
  - id: first-read
    match:
      tool: read_file
      path: important.txt
    sequence:
      - result: error
        code: EIO
        message: first attempt fails
      - result: passthrough
""",
        encoding="utf-8",
    )
    controller = FaultController.load([script])
    first = ToolCall(call_id="one", name="read_file", arguments={"path": "important.txt"})
    second = ToolCall(call_id="two", name="read_file", arguments={"path": "important.txt"})

    injected = controller.before(first)
    assert injected is not None
    assert injected.status == "error"
    assert injected.metadata["fault_rule"] == "first-read"
    assert controller.before(second) is None
    passthrough = ToolResult(call_id="two", name="read_file", status="ok", output="truth")
    assert controller.after(second, passthrough).output == "truth"
