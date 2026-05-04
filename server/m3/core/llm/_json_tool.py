"""Shared JSON-tool helpers used by providers without native tool dispatch.

OllamaProvider and LocalAgentProvider both fall back to "ask the model for
JSON matching this schema, then parse." The parsing logic is identical and
lives here so neither provider forks it.

Public surface:
- ``build_tool_prompt(tool, schema_str_only=True)`` -- the user-facing prompt
  appended after the regular messages telling the model to emit only JSON
  matching the tool's schema.
- ``parse_tool_response(text, tool, raw_response=None)`` -- coerces a free-form
  model reply into a ``ToolResult``. Strips markdown fences, trims to the
  outermost ``{...}`` block, recovers single-key stringified payloads, and
  raises ``ValueError`` if nothing parses.
- ``satisfies_required(args, schema)`` -- cheap presence check for the
  schema's ``required`` keys, exposed because OllamaProvider also uses it on
  the native tool-call path before falling back.
"""

from __future__ import annotations

import json
import re

from m3.core.llm.base import Tool, ToolResult


def satisfies_required(args: dict, schema: dict) -> bool:
    """True iff every key listed in ``schema['required']`` is present in args."""
    if not isinstance(args, dict):
        return False
    for key in (schema.get("required") or []):
        if key not in args:
            return False
    return True


def recover_stringified_payload(args: dict, schema: dict) -> dict:
    """Some small models wrap their JSON output under a single key whose value
    is a stringified JSON blob (e.g. ``{"map": '{"kind": "personal", ...}'}``).
    When that happens, try to unwrap the inner object."""
    if not isinstance(args, dict) or len(args) != 1:
        return args
    only_value = next(iter(args.values()))
    if not isinstance(only_value, str):
        return args
    try:
        inner = json.loads(only_value)
    except json.JSONDecodeError:
        return args
    if isinstance(inner, dict) and satisfies_required(inner, schema):
        return inner
    return args


def parse_json_blob(text: str) -> dict:
    """Pull a JSON object out of a free-form model reply.

    Tries (in order): the entire text, the contents of a ```json fenced block,
    and the substring between the first ``{`` and last ``}``. Raises
    ``ValueError`` if none parse.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1).strip())
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        return json.loads(text[start : end + 1])
    raise ValueError(f"could not parse JSON from response: {text[:200]}")


def build_tool_prompt(tool: Tool) -> str:
    """The user-facing instruction appended to make a non-tool-capable model
    emit JSON conforming to ``tool.input_schema``."""
    schema_str = json.dumps(tool.input_schema, indent=2)
    return (
        f"Call the `{tool.name}` tool. Reply with valid JSON only matching this schema:\n"
        f"{schema_str}\nNo prose, no fences."
    )


def parse_tool_response(text: str, tool: Tool, raw_response: dict | None = None) -> ToolResult:
    """Coerce a free-form model reply into a ToolResult for ``tool``."""
    parsed = parse_json_blob(text)
    parsed = recover_stringified_payload(parsed, tool.input_schema)
    return ToolResult(
        tool_name=tool.name,
        input=parsed,
        stop_reason="tool_use",
        text="",
        raw_response=raw_response or {},
    )
