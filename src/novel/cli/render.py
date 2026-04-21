"""Rendering helpers for the ``novel propose / accept / regenerate`` CLI group.

All helpers are tolerant of *either*:

* a ``ProposalEnvelope`` / ``AcceptResult`` dataclass from
  ``src.novel.services.tool_facade`` (exposes ``.to_dict()``), or
* a plain ``dict`` (e.g. freshly loaded from a proposal JSON file).

Output formats
--------------
``json``   — ``json.dumps(..., ensure_ascii=False, indent=2)`` to stdout;
             script-friendly, easily piped.
``yaml``   — ``yaml.safe_dump(..., allow_unicode=True, sort_keys=False)`` if
             PyYAML is available; otherwise we fall back to ``json`` with a
             one-line warning on stderr.
``table``  — Human-friendly Rich table summarising the envelope (default).

The helpers intentionally do *not* raise on unexpected shapes: rendering
is a terminal concern and should degrade gracefully when upstream data
drifts.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from rich.console import Console
from rich.table import Table


# ---------------------------------------------------------------------------
# Dict normalisation
# ---------------------------------------------------------------------------


def _as_dict(obj: Any) -> dict[str, Any]:
    """Coerce ``obj`` to a plain dict.

    Supports dataclasses with ``to_dict()`` (our ``ProposalEnvelope`` /
    ``AcceptResult``) and raw ``dict`` instances. Anything else is wrapped
    with a best-effort string repr under the ``value`` key so rendering
    never crashes.
    """
    if isinstance(obj, dict):
        return obj
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        result = to_dict()
        if isinstance(result, dict):
            return result
    return {"value": str(obj)}


# ---------------------------------------------------------------------------
# Output format dispatch
# ---------------------------------------------------------------------------


def _dump_json(payload: dict[str, Any], *, console: Console | None = None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    # json mode must go to plain stdout (pipe-friendly), bypassing Rich styling.
    print(text)


def _dump_yaml(payload: dict[str, Any], *, console: Console | None = None) -> None:
    try:
        import yaml  # type: ignore
    except ImportError:
        print(
            "[warn] PyYAML not installed; falling back to JSON output",
            file=sys.stderr,
        )
        _dump_json(payload)
        return
    text = yaml.safe_dump(
        payload,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    print(text)


# ---------------------------------------------------------------------------
# Rich table renderers
# ---------------------------------------------------------------------------


def _preview(value: Any, max_len: int = 120) -> str:
    """Shorten a value for table display without exploding on nested dicts."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        try:
            s = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            s = str(value)
    else:
        s = str(value)
    s = s.replace("\n", " ")
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def _render_envelope_table(
    payload: dict[str, Any],
    *,
    console: Console | None = None,
) -> None:
    """Render a ProposalEnvelope dict as a Rich table."""
    c = console or Console()

    table = Table(title="Proposal")
    table.add_column("字段", style="cyan")
    table.add_column("值", style="green")

    proposal_id = payload.get("proposal_id", "")
    proposal_type = payload.get("proposal_type", "")
    project_path = payload.get("project_path", "")
    created_at = payload.get("created_at", "")

    table.add_row("proposal_id", str(proposal_id))
    table.add_row("proposal_type", str(proposal_type))
    if project_path:
        table.add_row("project_path", str(project_path))
    if created_at:
        table.add_row("created_at", str(created_at))

    c.print(table)

    # Data preview — top-level keys only, values truncated.
    data = payload.get("data") or {}
    if isinstance(data, dict) and data:
        data_table = Table(title="Data 预览")
        data_table.add_column("key", style="cyan")
        data_table.add_column("value", style="white")
        for k, v in data.items():
            data_table.add_row(str(k), _preview(v))
        c.print(data_table)

    # Decisions / errors / warnings — one table each if present.
    decisions = payload.get("decisions") or []
    if decisions:
        dec_table = Table(title="Decisions")
        dec_table.add_column("agent", style="cyan")
        dec_table.add_column("step", style="white")
        dec_table.add_column("decision", style="green")
        for d in decisions:
            if not isinstance(d, dict):
                continue
            dec_table.add_row(
                str(d.get("agent", "")),
                str(d.get("step", "")),
                str(d.get("decision", "")),
            )
        c.print(dec_table)

    errors = payload.get("errors") or []
    if errors:
        err_table = Table(title="Errors")
        err_table.add_column("message", style="red")
        for e in errors:
            if isinstance(e, dict):
                err_table.add_row(str(e.get("message") or e))
            else:
                err_table.add_row(str(e))
        c.print(err_table)

    warnings = payload.get("warnings") or []
    if warnings:
        warn_table = Table(title="Warnings")
        warn_table.add_column("message", style="yellow")
        for w in warnings:
            warn_table.add_row(str(w))
        c.print(warn_table)


def _render_accept_table(
    payload: dict[str, Any],
    *,
    console: Console | None = None,
) -> None:
    """Render an AcceptResult dict as a Rich table."""
    c = console or Console()

    status = payload.get("status", "")
    table = Table(title="Accept 结果")
    table.add_column("字段", style="cyan")
    table.add_column("值", style="green")

    table.add_row("status", str(status))
    if "proposal_id" in payload:
        table.add_row("proposal_id", str(payload.get("proposal_id", "")))
    if "proposal_type" in payload:
        table.add_row("proposal_type", str(payload.get("proposal_type", "")))
    if payload.get("changelog_id"):
        table.add_row("changelog_id", str(payload.get("changelog_id")))
    if payload.get("error"):
        table.add_row("error", str(payload.get("error")))

    c.print(table)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_envelope(
    envelope: Any,
    output: str = "table",
    *,
    console: Console | None = None,
) -> dict[str, Any]:
    """Render a proposal envelope and return the normalised dict.

    Returning the dict lets callers feed it into a subsequent ``accept``
    call (e.g. ``--auto-accept``) without having to re-serialise.
    """
    payload = _as_dict(envelope)
    fmt = (output or "table").lower()
    if fmt == "json":
        _dump_json(payload, console=console)
    elif fmt == "yaml":
        _dump_yaml(payload, console=console)
    else:
        _render_envelope_table(payload, console=console)
    return payload


def render_accept_result(
    result: Any,
    output: str = "table",
    *,
    console: Console | None = None,
) -> dict[str, Any]:
    """Render an accept result in the chosen format."""
    payload = _as_dict(result)
    fmt = (output or "table").lower()
    if fmt == "json":
        _dump_json(payload, console=console)
    elif fmt == "yaml":
        _dump_yaml(payload, console=console)
    else:
        _render_accept_table(payload, console=console)
    return payload


__all__ = ["render_envelope", "render_accept_result"]
