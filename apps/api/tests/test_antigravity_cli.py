import json
import signal
import subprocess

from app.antigravity_cli import (
    ANTIGRAVITY_AGENT,
    AntigravityResult,
    _terminate_process_group,
    antigravity_environment,
    antigravity_process_error,
    parse_antigravity_models,
    prepare_antigravity_environment,
)
from app.config import get_settings


def test_managed_antigravity_profile_denies_local_tools(
    tmp_path,
    monkeypatch,
) -> None:
    settings = get_settings()
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(settings, "antigravity_home", home)
    monkeypatch.setattr(settings, "antigravity_workspace", workspace)

    prepare_antigravity_environment()

    managed = json.loads((home / ".gemini" / "antigravity-cli" / "settings.json").read_text())
    assert managed["toolPermission"] == "strict"
    assert managed["allowNonWorkspaceAccess"] is False
    assert managed["enableTelemetry"] is False
    assert set(managed["permissions"]["deny"]) >= {
        "read_file(*)",
        "write_file(*)",
        "read_url(*)",
        "command(*)",
        "mcp(*)",
    }
    agent = (home / ".gemini" / "config" / "agents" / ANTIGRAVITY_AGENT / "agent.md").read_text()
    assert "tools: []" in agent
    assert "no local tools" in agent.casefold()


def test_antigravity_subprocess_environment_excludes_control_secrets(
    tmp_path,
    monkeypatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "antigravity_home", tmp_path / "home")
    monkeypatch.setenv("APP_SECRET", "must-not-leak")
    monkeypatch.setenv("DATABASE_URL", "must-not-leak")
    monkeypatch.setenv("DOCKER_HOST", "must-not-leak")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.test")

    environment = antigravity_environment()

    assert environment["HTTPS_PROXY"] == "http://proxy.test"
    assert environment["AGY_CLI_DISABLE_AUTO_UPDATE"] == "1"
    assert environment["AGY_CLI_HIDE_ACCOUNT_INFO"] == "1"
    assert environment["CI"] == "1"
    assert "APP_SECRET" not in environment
    assert "DATABASE_URL" not in environment
    assert "DOCKER_HOST" not in environment


def test_antigravity_model_catalog_parser_accepts_public_cli_formats() -> None:
    models = parse_antigravity_models(
        """
        Available models:
          Gemini 3.1 Pro (High) (gemini-3.1-pro-high)
          claude-sonnet-4.6-thinking  Claude Sonnet 4.6 (Thinking)
          gpt-oss-120b-medium
          Gemini 3.1 Pro (High) (gemini-3.1-pro-high)
        """
    )

    assert [model.model_id for model in models] == [
        "gemini-3.1-pro-high",
        "claude-sonnet-4.6-thinking",
        "gpt-oss-120b-medium",
    ]
    assert models[0].display_name == "Gemini 3.1 Pro (High)"
    assert models[1].display_name == "Claude Sonnet 4.6 (Thinking)"
    assert models[2].display_name == "GPT OSS 120b Medium"


def test_antigravity_authentication_error_is_actionable() -> None:
    error = antigravity_process_error(
        AntigravityResult(
            returncode=1,
            stdout="",
            stderr="Error: Please sign in to view available models.",
        ),
        operation="model discovery",
    )

    assert error.authentication is True
    assert error.transient is False
    assert error.code == "antigravity_cli_needs_login"
    assert "make antigravity-login" in str(error)


def test_antigravity_timeout_terminates_the_entire_process_group(
    monkeypatch,
) -> None:
    signals: list[tuple[int, int]] = []

    class Process:
        pid = 321

        def __init__(self) -> None:
            self.communications = 0

        def communicate(self, timeout=None):
            self.communications += 1
            if timeout == 2:
                raise subprocess.TimeoutExpired("agy", timeout)
            return "", ""

    process = Process()
    monkeypatch.setattr(
        "app.antigravity_cli.os.killpg",
        lambda pid, sent_signal: signals.append((pid, sent_signal)),
    )

    _terminate_process_group(process)

    assert signals == [
        (321, signal.SIGTERM),
        (321, signal.SIGKILL),
    ]
    assert process.communications == 2
