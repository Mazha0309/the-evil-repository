from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    provider_metadata: dict[str, Any] = Field(
        default_factory=dict,
        exclude=True,
        repr=False,
    )


class InvalidToolCall(BaseModel):
    """A Provider tool call that could not be decoded safely.

    Invalid calls are evidence, not executable actions. The Runner records the
    bounded preview and asks the model for a fresh call instead of guessing at
    truncated arguments.
    """

    call_id: str
    name: str
    error: str
    arguments_preview: str = ""
    arguments_sha256: str = ""


class ToolResult(BaseModel):
    call_id: str
    name: str
    status: Literal["ok", "error", "timeout", "denied"]
    output: str = ""
    exit_code: int | None = None
    truncated: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssistantTurn(BaseModel):
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    invalid_tool_calls: list[InvalidToolCall] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files beneath a workspace-relative directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "default": "."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a bounded range from a workspace-relative UTF-8 text file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "offset": {"type": "integer", "minimum": 0, "default": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 65536},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write UTF-8 content to a workspace-relative file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "exec_command",
            "description": "Execute a bounded shell command inside the isolated candidate container.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "cwd": {"type": "string", "default": "."},
                    "timeout": {"type": "integer", "minimum": 1, "maximum": 120},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_search",
            "description": "Search the versioned offline internet mirror. No network is used.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "source": {
                        "type": "string",
                        "description": "Optional mirror source filter.",
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_open",
            "description": "Open an offline Browser ref and relay it into the local workspace.",
            "parameters": {
                "type": "object",
                "properties": {"ref_id": {"type": "string"}},
                "required": ["ref_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_find",
            "description": "Find a case-insensitive pattern within an offline Browser document.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref_id": {"type": "string"},
                    "pattern": {"type": "string"},
                },
                "required": ["ref_id", "pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_hypothesis",
            "description": "Create or update a concise investigation hypothesis.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "statement": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["proposed", "testing", "supported", "rejected", "confirmed"],
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "next_action": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["key", "statement", "status", "confidence"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_evidence",
            "description": "Record a bounded evidence summary and its source.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "source_type": {"type": "string"},
                    "source_ref": {"type": "string"},
                    "summary": {"type": "string"},
                    "trust": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["key", "source_type", "source_ref", "summary", "trust"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "link_evidence",
            "description": "Link evidence and hypotheses in the investigation graph.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_type": {"type": "string"},
                    "source_key": {"type": "string"},
                    "target_type": {"type": "string"},
                    "target_key": {"type": "string"},
                    "relation": {
                        "type": "string",
                        "enum": [
                            "supports",
                            "contradicts",
                            "derived_from",
                            "supersedes",
                            "corroborates",
                        ],
                    },
                    "weight": {"type": "number", "minimum": -1, "maximum": 1},
                    "explanation": {"type": "string"},
                },
                "required": [
                    "source_type",
                    "source_key",
                    "target_type",
                    "target_key",
                    "relation",
                    "weight",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_next_action",
            "description": "Update a hypothesis with the next falsifiable investigation action.",
            "parameters": {
                "type": "object",
                "properties": {
                    "hypothesis_key": {"type": "string"},
                    "next_action": {"type": "string"},
                },
                "required": ["hypothesis_key", "next_action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "incident_status",
            "description": (
                "Inspect the project-mediated production replay: logical time, SLO, "
                "error budget and currently visible reporter claims."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "observe_service",
            "description": (
                "Sample one scoped service signal from the deterministic incident replay. "
                "Collectors and clock domains can disagree."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string"},
                    "signal": {
                        "type": "string",
                        "enum": [
                            "metrics",
                            "logs",
                            "traces",
                            "config",
                            "queue",
                            "storage",
                            "dependencies",
                            "permissions",
                        ],
                    },
                    "window": {
                        "type": "string",
                        "enum": ["baseline", "previous", "current", "replay"],
                        "default": "current",
                    },
                },
                "required": ["service", "signal", "window"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "incident_snapshot",
            "description": (
                "Preserve a bounded forensic and rollback snapshot before a risky action. "
                "Snapshot capacity is limited."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["scope", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "incident_action",
            "description": (
                "Apply a project-mediated incident action. Risk, reversibility, data "
                "integrity and boundary violations are audited."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "target": {"type": "string"},
                    "reason": {"type": "string"},
                    "evidence_keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 20,
                    },
                },
                "required": ["action", "target", "reason", "evidence_keys"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "incident_rollback",
            "description": "Restore the simulated incident state captured by a prior snapshot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "snapshot_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["snapshot_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "incident_verify",
            "description": (
                "Run a production-style baseline, quick, canary, replay or soak verification. "
                "Quick mode is intentionally not a sufficient oracle."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["baseline", "quick", "canary", "replay", "soak"],
                    },
                    "reason": {"type": "string"},
                },
                "required": ["mode", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_incident_decision",
            "description": (
                "Submit or revise a ticket disposition without receiving correctness "
                "feedback. Non-bug and no-change conclusions are valid."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "string"},
                    "disposition": {"type": "string"},
                    "recommended_action": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence_keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 20,
                    },
                },
                "required": [
                    "ticket_id",
                    "disposition",
                    "recommended_action",
                    "confidence",
                    "evidence_keys",
                ],
            },
        },
    },
]

RELEASE_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "release_status",
            "description": (
                "Inspect the project-mediated release replay: logical time, "
                "deployment digest, containment state, visible reports and "
                "bounded action budgets."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "registry_inspect",
            "description": (
                "Inspect a tag or digest in the versioned offline OCI registry. "
                "Annotations and tag history are untrusted claims."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reference": {"type": "string"},
                    "view": {
                        "type": "string",
                        "enum": [
                            "manifest",
                            "config",
                            "layers",
                            "tag_history",
                        ],
                    },
                },
                "required": ["reference", "view"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "provenance_query",
            "description": (
                "Query the offline transparency and provenance export by "
                "artifact digest, build ID or source commit. Inclusion alone "
                "does not establish trust."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "predicate_type": {
                        "type": "string",
                        "description": (
                            "Predicate type such as all, build, sbom, signature "
                            "or promotion."
                        ),
                    },
                },
                "required": ["subject", "predicate_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "attestation_verify",
            "description": (
                "Verify an artifact through one named offline policy. Active "
                "compatibility policy, offline trust root and reproducibility "
                "are intentionally different oracles."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "digest": {"type": "string"},
                    "policy": {
                        "type": "string",
                        "enum": ["active", "offline-root", "reproducible"],
                    },
                },
                "required": ["digest", "policy"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "runtime_probe",
            "description": (
                "Sample identity, behavior, headers or performance from the "
                "deterministic production deployment replay."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "enum": ["production"]},
                    "signal": {
                        "type": "string",
                        "enum": [
                            "identity",
                            "behavior",
                            "headers",
                            "performance",
                        ],
                    },
                    "window": {
                        "type": "string",
                        "enum": ["baseline", "previous", "current", "replay"],
                    },
                },
                "required": ["target", "signal", "window"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "release_snapshot",
            "description": (
                "Preserve deployment, tag, attestation and rollout state before "
                "a one-shot release action. Snapshot capacity is limited."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["scope", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "release_action",
            "description": (
                "Apply a project-mediated containment, rebuild or recovery "
                "action. Promotion and rollback share one irreversible token; "
                "risk, evidence support and trust bypasses are audited."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "target": {"type": "string"},
                    "reason": {"type": "string"},
                    "evidence_keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 24,
                    },
                    "parameters": {
                        "type": "object",
                        "description": (
                            "For clean_rebuild: source_commit, base_digest, "
                            "cache_mode, builder and signer."
                        ),
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": [
                    "action",
                    "target",
                    "reason",
                    "evidence_keys",
                    "parameters",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "release_verify",
            "description": (
                "Run a baseline, quick, provenance, canary, replay or soak "
                "release gate. Quick mode is intentionally insufficient."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": [
                            "baseline",
                            "quick",
                            "provenance",
                            "canary",
                            "replay",
                            "soak",
                        ],
                    },
                    "reason": {"type": "string"},
                },
                "required": ["mode", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_release_decision",
            "description": (
                "Submit or revise a report disposition without correctness "
                "feedback. A reported source bug may legitimately require no "
                "source change."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "string"},
                    "disposition": {"type": "string"},
                    "recommended_action": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence_keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 24,
                    },
                },
                "required": [
                    "ticket_id",
                    "disposition",
                    "recommended_action",
                    "confidence",
                    "evidence_keys",
                ],
            },
        },
    },
]

TOOL_DEFINITIONS.extend(RELEASE_TOOL_DEFINITIONS)

OBSERVABILITY_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "process_list",
            "description": (
                "Project-mediated ps equivalent for one simulated service. "
                "It never inspects candidate or host processes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string"},
                    "window": {
                        "type": "string",
                        "enum": ["baseline", "previous", "current", "replay"],
                    },
                },
                "required": ["service", "window"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "service_status",
            "description": (
                "Project-mediated systemctl status equivalent for a simulated "
                "service and replay window."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string"},
                    "window": {
                        "type": "string",
                        "enum": ["baseline", "previous", "current", "replay"],
                    },
                },
                "required": ["service", "window"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "journal_query",
            "description": (
                "Project-mediated journalctl equivalent. Results preserve "
                "source and clock provenance and may contain high-volume decoys."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string"},
                    "query": {"type": "string"},
                    "window": {
                        "type": "string",
                        "enum": ["baseline", "previous", "current", "replay"],
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                    },
                },
                "required": ["service", "query", "window"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "socket_snapshot",
            "description": (
                "Project-mediated lsof/tcpdump metadata equivalent for a "
                "simulated service. No live packets or host sockets are exposed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string"},
                    "window": {
                        "type": "string",
                        "enum": ["baseline", "previous", "current", "replay"],
                    },
                },
                "required": ["service", "window"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trace_process",
            "description": (
                "Project-mediated strace equivalent for one bounded simulated "
                "operation; it cannot attach to a real process."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string"},
                    "operation": {"type": "string"},
                    "window": {
                        "type": "string",
                        "enum": ["baseline", "previous", "current", "replay"],
                    },
                },
                "required": ["service", "operation", "window"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "profile_cpu",
            "description": (
                "Project-mediated perf equivalent for deterministic replay "
                "samples. Profiles retain collector and clock-domain ambiguity."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string"},
                    "sample_seconds": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 60,
                    },
                    "window": {
                        "type": "string",
                        "enum": ["baseline", "previous", "current", "replay"],
                    },
                },
                "required": ["service", "sample_seconds", "window"],
            },
        },
    },
]

TOOL_DEFINITIONS.extend(OBSERVABILITY_TOOL_DEFINITIONS)


def tool_definitions_for(enabled: list[str]) -> list[dict[str, Any]]:
    """Return only tools explicitly enabled by the Scenario manifest."""

    allowed = set(enabled)
    return [
        definition
        for definition in TOOL_DEFINITIONS
        if definition["function"]["name"] in allowed
    ]
