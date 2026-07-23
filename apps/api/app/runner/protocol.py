from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


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
]
