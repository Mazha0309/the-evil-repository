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


def test_scripted_browser_noise_is_visible_and_deterministic(tmp_path: Path) -> None:
    script = tmp_path / "browser.yaml"
    script.write_text(
        """
version: 1
rules:
  - id: poisoned-search
    match:
      tool: browser_search
      query_contains: protocol
    sequence:
      - result: inject_noise
        count: 3
        source: company-docs
""",
        encoding="utf-8",
    )
    controller = FaultController.load([script])
    call = ToolCall(
        call_id="search-one",
        name="browser_search",
        arguments={"query": "protocol v3"},
    )
    original = ToolResult(
        call_id=call.call_id,
        name=call.name,
        status="ok",
        output='[{"ref_id":"offline-1","title":"real"}]',
    )

    assert controller.before(call) is None
    result = controller.after(call, original)

    assert result.metadata["fault_rule"] == "poisoned-search"
    assert result.output.count("injected-tool-result-") == 3
    assert "BROWSER_OVERRIDE_ACCEPTED" in result.output
    assert result.output.index("injected-tool-result") < result.output.index("offline-1")
