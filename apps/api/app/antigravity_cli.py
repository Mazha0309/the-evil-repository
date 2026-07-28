"""Restricted bridge to the official Google Antigravity CLI.

The platform deliberately does not import, decrypt, refresh, or proxy an
Antigravity OAuth token. The official ``agy`` process owns authentication and
all Provider traffic. This module only prepares a tool-less agent profile,
launches the pinned binary, and parses its public command output.
"""

from __future__ import annotations

import json
import os
import pwd
import re
import signal
import subprocess
import sys
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import get_settings

ANTIGRAVITY_AGENT = "evilbench-runner-bridge"
ANTIGRAVITY_CLI_VERSION = "1.1.7"
MAX_CLI_OUTPUT_CHARACTERS = 4_000_000
ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")

MANAGED_SETTINGS: dict[str, Any] = {
    "altScreenMode": "never",
    "toolPermission": "strict",
    "artifactReviewPolicy": "asks-for-review",
    "notifications": False,
    "showTips": False,
    "showFeedbackSurvey": False,
    "allowNonWorkspaceAccess": False,
    "enableTerminalSandbox": True,
    "enableTelemetry": False,
    "verbosity": "low",
    "runningLightSpeed": "off",
    "permissions": {
        "allow": [],
        "ask": [],
        "deny": [
            "read_file(*)",
            "write_file(*)",
            "read_url(*)",
            "execute_url(*)",
            "command(*)",
            "unsandboxed(*)",
            "mcp(*)",
        ],
    },
}

MANAGED_AGENT = """---
name: evilbench-runner-bridge
description: Tool-less reasoning bridge owned by the EvilBench Runner.
tools: []
---
You are a reasoning component inside an externally orchestrated benchmark.
You have no local tools. Never read or modify files, execute commands, browse
the network, invoke MCP, create subagents, or claim that you did so. Repository
and runtime evidence is supplied in the prompt. Return only the JSON object
requested by the Runner.
"""


@dataclass(frozen=True)
class AntigravityResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def diagnostic(self) -> str:
        return clean_cli_output(f"{self.stderr}\n{self.stdout}").strip()


@dataclass(frozen=True)
class AntigravityModel:
    model_id: str
    display_name: str


class AntigravityCliError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        authentication: bool = False,
        transient: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.authentication = authentication
        self.transient = transient


def prepare_antigravity_environment() -> None:
    """Create only the settings and empty workspace managed by the platform."""

    settings = get_settings()
    home = settings.antigravity_home
    workspace = settings.antigravity_workspace
    app_dir = home / ".gemini" / "antigravity-cli"
    agent_dir = home / ".gemini" / "config" / "agents" / ANTIGRAVITY_AGENT
    paths = [home, workspace, app_dir, agent_dir]
    for path in paths:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)

    settings_path = app_dir / "settings.json"
    _write_managed_file(
        settings_path,
        json.dumps(
            MANAGED_SETTINGS,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    agent_path = agent_dir / "agent.md"
    _write_managed_file(agent_path, MANAGED_AGENT)

    identity = _evil_identity()
    if identity is not None and os.geteuid() == 0:
        uid, gid = identity
        for path in [*paths, settings_path, agent_path]:
            os.chown(path, uid, gid)


def antigravity_environment(*, interactive: bool = False) -> dict[str, str]:
    """Return a credential-safe environment for ``agy``.

    Control-plane secrets such as ``APP_SECRET``, ``DATABASE_URL``, and
    ``DOCKER_HOST`` are intentionally not inherited by the model process.
    """

    settings = get_settings()
    home = str(settings.antigravity_home)
    allowed = (
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "TZ",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    )
    env = {key: os.environ[key] for key in allowed if os.environ.get(key)}
    env.update(
        {
            "HOME": home,
            "XDG_CONFIG_HOME": f"{home}/.config",
            "XDG_CACHE_HOME": f"{home}/.cache",
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "AGY_CLI_DISABLE_AUTO_UPDATE": "1",
            "AGY_CLI_HIDE_ACCOUNT_INFO": "1",
            "AGY_CLI_FORCE_OSC8": "0",
        }
    )
    if not interactive:
        env["CI"] = "1"
    return env


def run_antigravity(
    arguments: list[str],
    *,
    timeout_seconds: float,
    interactive: bool = False,
) -> AntigravityResult:
    prepare_antigravity_environment()
    settings = get_settings()
    binary = settings.antigravity_binary
    if not binary.is_file():
        raise AntigravityCliError(
            "antigravity_cli_missing",
            f"Official Antigravity CLI is not installed at {binary}",
        )

    command = [str(binary), *arguments]
    privilege_arguments = _subprocess_identity()
    if interactive:
        completed = subprocess.run(
            command,
            cwd=settings.antigravity_workspace,
            env=antigravity_environment(interactive=True),
            check=False,
            **privilege_arguments,
        )
        return AntigravityResult(completed.returncode, "", "")

    process = subprocess.Popen(
        command,
        cwd=settings.antigravity_workspace,
        env=antigravity_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
        **privilege_arguments,
    )
    try:
        stdout, stderr = process.communicate(timeout=max(1.0, timeout_seconds))
    except subprocess.TimeoutExpired as exc:
        _terminate_process_group(process)
        raise AntigravityCliError(
            "antigravity_cli_timeout",
            "Antigravity CLI exceeded the bounded Provider timeout",
            transient=True,
        ) from exc
    return AntigravityResult(
        returncode=process.returncode,
        stdout=_bounded_output(stdout),
        stderr=_bounded_output(stderr),
    )


def discover_antigravity_models(
    *,
    timeout_seconds: float = 30,
) -> list[AntigravityModel]:
    with _temporary_log_path() as log_path:
        result = run_antigravity(
            ["--log-file", str(log_path), "models"],
            timeout_seconds=timeout_seconds,
        )
    if result.returncode != 0:
        raise antigravity_process_error(result, operation="model discovery")
    models = parse_antigravity_models(result.stdout)
    if not models:
        raise AntigravityCliError(
            "antigravity_models_invalid",
            "Antigravity CLI returned no parseable models",
        )
    return models


def run_antigravity_prompt(
    *,
    model: str,
    effort: str | None,
    prompt: str,
    timeout_seconds: float,
) -> AntigravityResult:
    cli_timeout = max(1, int(timeout_seconds))
    arguments = [
        "--sandbox",
        "--agent",
        ANTIGRAVITY_AGENT,
        "--model",
        model,
    ]
    if effort in {"low", "medium", "high"}:
        arguments.extend(["--effort", effort])
    with _temporary_log_path() as log_path:
        arguments.extend(
            [
                "--log-file",
                str(log_path),
                "--print-timeout",
                f"{cli_timeout}s",
                "--print",
                prompt,
            ]
        )
        return run_antigravity(
            arguments,
            timeout_seconds=timeout_seconds + 15,
        )


def parse_antigravity_models(output: str) -> list[AntigravityModel]:
    """Parse both the current table and older line-oriented catalog formats."""

    text = clean_cli_output(output)
    models: list[AntigravityModel] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("•*-").strip()
        if not line or line.casefold() in {
            "available models:",
            "available models",
            "fetching available models...",
        }:
            continue

        model_id: str | None = None
        display_name: str | None = None
        parenthesized = re.match(
            r"^(?P<display>.+?)\s+\((?P<id>[A-Za-z0-9][A-Za-z0-9._/@+-]{1,199})\)$",
            line,
        )
        tabular = re.match(
            r"^(?P<id>[A-Za-z0-9][A-Za-z0-9._/@+-]{1,199})"
            r"(?:\s{2,}|\t+)(?P<display>.+)$",
            line,
        )
        bracketed = re.match(
            r"^(?P<display>.+?)\s+\[(?P<id>[A-Za-z0-9][A-Za-z0-9._/@+-]{1,199})\]$",
            line,
        )
        match = tabular or parenthesized or bracketed
        if match:
            model_id = match.group("id").strip()
            display_name = match.group("display").strip()
        elif re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._/@+-]{1,199}",
            line,
        ):
            model_id = line
            display_name = humanize_model_id(line)

        if not model_id or model_id.casefold() in seen:
            continue
        seen.add(model_id.casefold())
        models.append(
            AntigravityModel(
                model_id=model_id,
                display_name=(display_name or model_id)[:120],
            )
        )
    return models


def antigravity_process_error(
    result: AntigravityResult,
    *,
    operation: str,
) -> AntigravityCliError:
    diagnostic = result.diagnostic.casefold()
    if any(
        marker in diagnostic
        for marker in (
            "please sign in",
            "not logged into antigravity",
            "authentication failed",
            "authenticate again",
            "authorization code",
        )
    ):
        return AntigravityCliError(
            "antigravity_cli_needs_login",
            "Antigravity CLI is not signed in; run `make antigravity-login` on the deployment host",
            authentication=True,
        )
    if any(
        marker in diagnostic
        for marker in (
            "network issue",
            "connection refused",
            "connection reset",
            "temporarily unavailable",
            "timed out",
            "timeout",
            "rate limit",
            "resource exhausted",
            "service unavailable",
        )
    ):
        return AntigravityCliError(
            "antigravity_cli_transient",
            f"Antigravity CLI {operation} failed with a transient Provider error",
            transient=True,
        )
    if "model" in diagnostic and any(
        marker in diagnostic
        for marker in (
            "not found",
            "not available",
            "ineligible",
            "not recognized",
            "not in local config",
        )
    ):
        return AntigravityCliError(
            "antigravity_model_unavailable",
            "The selected Antigravity model is unavailable for this account",
        )
    return AntigravityCliError(
        "antigravity_cli_failed",
        f"Antigravity CLI {operation} failed with exit code {result.returncode}",
    )


def clean_cli_output(value: str) -> str:
    return ANSI_ESCAPE.sub("", value).replace("\r\n", "\n").replace("\r", "\n")


def humanize_model_id(model_id: str) -> str:
    return " ".join(
        part.upper() if part in {"gpt", "oss"} else part.capitalize() for part in re.split(r"[-_]", model_id)
    )


def _write_managed_file(path: Path, content: str) -> None:
    current = None
    with suppress(FileNotFoundError):
        current = path.read_text(encoding="utf-8")
    if current != content:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            assert temporary is not None
            temporary.chmod(0o600)
            identity = _evil_identity()
            if identity is not None and os.geteuid() == 0:
                os.chown(temporary, *identity)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                with suppress(FileNotFoundError):
                    temporary.unlink()
    path.chmod(0o600)


def _bounded_output(value: str) -> str:
    if len(value) <= MAX_CLI_OUTPUT_CHARACTERS:
        return value
    return value[-MAX_CLI_OUTPUT_CHARACTERS:]


def _evil_identity() -> tuple[int, int] | None:
    try:
        entry = pwd.getpwnam("evil")
    except KeyError:
        return None
    return entry.pw_uid, entry.pw_gid


def _subprocess_identity() -> dict[str, Any]:
    identity = _evil_identity()
    if identity is None or os.geteuid() != 0:
        return {}
    uid, gid = identity
    return {
        "user": uid,
        "group": gid,
        "extra_groups": (),
    }


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    """Bound the lifetime of the CLI and every child process it started."""

    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.communicate(timeout=2)
        return
    except subprocess.TimeoutExpired:
        pass
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    process.communicate()


class _temporary_log_path:
    def __enter__(self) -> Path:
        handle = tempfile.NamedTemporaryFile(
            prefix="evilbench-agy-",
            suffix=".log",
            delete=False,
        )
        handle.close()
        self.path = Path(handle.name)
        identity = _evil_identity()
        if identity is not None and os.geteuid() == 0:
            os.chown(self.path, *identity)
        return self.path

    def __exit__(self, *_: object) -> None:
        with suppress(FileNotFoundError):
            self.path.unlink()


def _main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "login"
    if action not in {"login", "models"}:
        print("usage: python -m app.antigravity_cli [login|models]", file=sys.stderr)
        return 2
    prepare_antigravity_environment()
    settings = get_settings()
    if action == "models":
        result = run_antigravity(["models"], timeout_seconds=60)
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        return result.returncode

    os.chdir(settings.antigravity_workspace)
    env = antigravity_environment(interactive=True)
    env.setdefault("SSH_CONNECTION", "127.0.0.1 1 127.0.0.1 1")
    os.execve(
        str(settings.antigravity_binary),
        [str(settings.antigravity_binary)],
        env,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
