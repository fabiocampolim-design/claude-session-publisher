#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transcript_archiver.py -- turn a Claude conversation into a self-contained
document (HTML, plain text, Markdown, LaTeX or PDF) with a fidelity report
proving nothing was silently dropped.

Every record in the source .jsonl is parsed into a typed model and either
rendered, folded into an earlier turn, or counted -- and the three numbers are
reconciled against the source record count on the page itself.

USAGE
    python transcript_archiver.py <session-id> [--title "..."] [options]
    python transcript_archiver.py <id> --format html,text,markdown,latex,pdf
    python transcript_archiver.py <id> --format latex --fragment   # body only
    python transcript_archiver.py --import-claude-ai conversations.json
    python transcript_archiver.py --index [--watch 300]

SOURCES
    Claude Code sessions (~/.claude/projects), Claude Desktop cowork sessions
    (--cowork-root, auto-detected) and claude.ai data exports
    (--import-claude-ai), all through one pipeline.

FORMATS
    All five render from the same parsed transcript, so a turn cannot appear in
    one format and vanish from another. pdf is the LaTeX compiled by xelatex;
    --fragment emits an engine-neutral body for \\input into your own paper.
    --tool-output on|off is independent of the format: full tool I/O turns a
    large session into a several-hundred-page document.

Human turns are reproduced verbatim in every format; every prompt and
response carries a citable tag (P1.., R1.., subagents A1.P1..). Thinking
blocks are empty in Claude Code transcripts (display=omitted) and the page
says so. The summary section is hand-written: pass --summary-file.

Full documentation: docs/USER_MANUAL.md (humans) and AGENTS.md (agents).
"""

from __future__ import annotations

import argparse
import datetime
import html
import json
import math
import os
import re
import sys
import subprocess
import shutil
import textwrap
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

esc = html.escape

VERSION = "2.6.1"

# Where archives go unless --archive-dir says otherwise. CLAUDE_ARCHIVE_DIR in
# the environment overrides the built-in default so a personal location never
# has to be hard-coded.
DEFAULT_ARCHIVE_DIR = Path(os.environ.get("CLAUDE_ARCHIVE_DIR")
                           or (Path.home() / "claude-archives"))


# ---------------------------------------------------------------------------
# Console output and the per-run audit log.
#   say()    -- normal progress, silenced by --quiet
#   detail() -- only with --verbose
#   note()   -- warnings, always shown (stderr)
# Everything said is also kept for the audit log written at the end of a run.
# ---------------------------------------------------------------------------

class _Console:
    def __init__(self):
        self.verbose = False
        self.quiet = False
        self.lines: list[str] = []

    def _keep(self, level: str, msg: str) -> None:
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.lines.append(f"{stamp} {level:<6} {msg}")

    def say(self, msg: str = "") -> None:
        self._keep("info", msg)
        if not self.quiet:
            print(msg)

    def detail(self, msg: str) -> None:
        self._keep("detail", msg)
        if self.verbose and not self.quiet:
            print(msg)

    def note(self, msg: str) -> None:
        self._keep("note", msg)
        print(msg, file=sys.stderr)


CON = _Console()


def write_audit_log(log_dir: Path, argv: list[str], started: datetime.datetime,
                    outcome: str, label: str = "run") -> Path | None:
    """One file per invocation: exact command line, versions, everything the
    run said, and how it ended. Never lets a logging failure kill the run."""
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        name = f"{started.strftime('%Y%m%d-%H%M%S')}_{slugify(label)[:40]}.log"
        ended = datetime.datetime.now()
        body = [
            f"transcript_archiver v{VERSION}",
            f"python {sys.version.split()[0]} on {sys.platform}",
            "command: " + " ".join(argv),
            f"cwd: {os.getcwd()}",
            f"started: {started.isoformat(timespec='seconds')}",
            f"ended:   {ended.isoformat(timespec='seconds')}",
            "",
            *CON.lines,
            "",
            f"outcome: {outcome}",
        ]
        path = log_dir / name
        path.write_text("\n".join(body) + "\n", encoding="utf-8")
        return path
    except OSError as e:
        print(f"note: could not write audit log: {e}", file=sys.stderr)
        return None

# ---------------------------------------------------------------------------
# Pricing (USD per million tokens, public list rates). Cost is an estimate at
# list price: it is not what a subscription actually bills, but it is the only
# figure that makes cache reads legible next to output tokens.
# ---------------------------------------------------------------------------

PRICING = {
    "claude-fable-5":            (10.00, 50.00),
    "claude-mythos-5":           (10.00, 50.00),
    "claude-opus-5":             (5.00, 25.00),
    "claude-opus-4-8":           (5.00, 25.00),
    "claude-opus-4-7":           (5.00, 25.00),
    "claude-opus-4-6":           (5.00, 25.00),
    "claude-opus-4-5":           (5.00, 25.00),
    "claude-sonnet-5":           (3.00, 15.00),
    "claude-sonnet-4-6":         (3.00, 15.00),
    "claude-sonnet-4-5":         (3.00, 15.00),
    "claude-haiku-4-5":          (1.00, 5.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
}
# Introductory rates that expire; (input, output, through-date).
INTRO_PRICING = {
    "claude-sonnet-5": (2.00, 10.00, datetime.date(2026, 8, 31)),
}
CACHE_READ_MULTIPLIER = 0.10
CACHE_WRITE_MULTIPLIER = {"5m": 1.25, "1h": 2.00}


def model_rates(model: str, on: datetime.date) -> tuple[float, float] | None:
    intro = INTRO_PRICING.get(model)
    if intro and on <= intro[2]:
        return intro[0], intro[1]
    return PRICING.get(model)


# ---------------------------------------------------------------------------
# Attachment / system record policy.
#   render   -> shown as a collapsed harness row
#   count    -> counted in the fidelity report only (pure plumbing, no content)
# ---------------------------------------------------------------------------

ATTACHMENT_POLICY = {
    "hook_success":            ("render", "Hook"),
    "hook_additional_context": ("render", "Hook context injected"),
    "hook_system_message":     ("render", "Hook message"),
    "skill_listing":           ("render", "Skill listing injected"),
    "invoked_skills":          ("render", "Skill invoked"),
    "nested_memory":           ("render", "Project memory injected"),
    "file":                    ("render", "File injected"),
    "edited_text_file":        ("render", "File edit snapshot"),
    "compact_file_reference":  ("render", "File carried through compaction"),
    "read_truncation_notice":  ("render", "Read truncated"),
    "deferred_tools_delta":    ("render", "Deferred tools changed"),
    "agent_listing_delta":     ("render", "Agent listing changed"),
    "mcp_instructions_delta":  ("render", "MCP instructions injected"),
    "command_permissions":     ("render", "Command permissions"),
    "task_reminder":           ("render", "Task reminder"),
    "queued_command":          ("render", "Command queued"),
    "date_change":             ("render", "Date changed"),
    "total_tokens_reminder":   ("count", "Token-budget reminder"),
}

SYSTEM_SUBTYPE_POLICY = {
    "turn_duration":       ("count", "Turn duration"),   # consumed as a metric
    "local_command":       ("render", "Local slash command"),
    "bridge_status":       ("render", "Session bridged"),
    "scheduled_task_fire": ("render", "Scheduled task fired"),
    "compact_boundary":    ("render", "Context compacted"),
}

# Record types that carry no transcript content: UI state, indexes, snapshots.
METADATA_RECORD_TYPES = {
    "last-prompt", "mode", "permission-mode", "ai-title", "queue-operation",
    "file-history-snapshot", "file-history-delta", "bridge-session",
    "frame-link", "agent-name", "summary",
    # worktree bookkeeping (Claude Code 2.1.x): where the session's cwd moved
    # to and which git worktree it entered -- state, not conversation
    "worktree-state", "relocated", "atis-latch",
    # Claude Code 2.1.9x: running cost/usage snapshot and artifact-comment
    # bookkeeping (which artifacts are watched, what has been replied to)
    "cost-state", "artifact-comment-monitor", "artifact-autoreact-ledger",
}


# ---------------------------------------------------------------------------
# Markdown -> HTML. Same scope as v1 (this is Claude's own prose, not arbitrary
# CommonMark) plus indentation-aware nested lists, which v1 flattened.
# ---------------------------------------------------------------------------

def inline_md(s: str) -> str:
    s = esc(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\*\w])\*([^*\n]+)\*(?![\*\w])", r"<em>\1</em>", s)
    s = re.sub(r"~~([^~]+)~~", r"<del>\1</del>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
               r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
    return s


# A numbered item is at most three digits: "2024. was a good year" is prose
# opening with a year, not item 2024 of a list.
_LIST_RE = re.compile(r"^(\s*)([-*+]|\d{1,3}[.)])\s+(.*)$")
_FENCE_RE = re.compile(r"^(`{3,})\s*(.*)$")


def _render_list(items: list[tuple[int, bool, str]], start: int = 0) -> tuple[str, int]:
    """items = [(indent, ordered, text)]; returns (html, index consumed)."""
    if not items:
        return "", start
    indent = items[start][0]
    ordered = items[start][1]
    tag = "ol" if ordered else "ul"
    out = [f"<{tag}>"]
    i = start
    while i < len(items):
        ind, orderd, text = items[i]
        if ind < indent:
            break
        if ind > indent:
            nested, i = _render_list(items, i)
            out.append(nested)
            continue
        if orderd != ordered:
            break
        out.append("<li>" + inline_md(text))
        # a deeper block immediately after belongs inside this <li>
        if i + 1 < len(items) and items[i + 1][0] > indent:
            nested, i = _render_list(items, i + 1)
            out.append(nested)
        else:
            i += 1
        out.append("</li>")
    out.append(f"</{tag}>")
    return "".join(out), i


def md_tokens(text: str) -> list[tuple]:
    """Scan markdown into typed blocks.

    Split out of md_to_html so HTML and LaTeX render from one parse instead of
    two copies that drift. Token shapes:
        ("para", str) ("code", lang, str) ("heading", level, str) ("hr",)
        ("table", header, rows) ("list", items) ("quote", str)
    """
    if not text:
        return []
    lines = text.replace("\r\n", "\n").split("\n")
    out: list[tuple] = []
    para: list[str] = []
    i, n = 0, len(lines)

    def flush():
        if para:
            out.append(("para", " ".join(para)))
            para.clear()

    while i < n:
        raw = lines[i]
        stripped = raw.strip()

        fence = _FENCE_RE.match(stripped)
        if fence:
            # The closing fence must be at least as long as the opening one, so
            # a ```` block can quote ``` without ending early, and the language
            # is whatever follows the run -- never a stray backtick.
            flush()
            ticks, lang = fence.group(1), fence.group(2).strip()
            close = re.compile(r"^`{%d,}\s*$" % len(ticks))
            i += 1
            code = []
            while i < n and not close.match(lines[i].strip()):
                code.append(lines[i])
                i += 1
            i += 1
            out.append(("code", lang, "\n".join(code)))
            continue

        if re.match(r"^#{1,6}\s+", stripped):
            flush()
            level = min(len(stripped) - len(stripped.lstrip("#")), 5)
            out.append(("heading", level, stripped.lstrip("#").strip()))
            i += 1
            continue

        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            flush()
            out.append(("hr",))
            i += 1
            continue

        if stripped.startswith("|") and i + 1 < n and re.match(r"^\|?[\s:|-]+\|?$", lines[i + 1].strip()):
            flush()
            header = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append(("table", header, rows))
            continue

        if _LIST_RE.match(raw):
            flush()
            items: list[tuple[int, bool, str]] = []
            while i < n:
                m = _LIST_RE.match(lines[i])
                if not m:
                    if lines[i].strip() == "" and i + 1 < n and _LIST_RE.match(lines[i + 1]):
                        i += 1
                        continue
                    break
                indent = len(m.group(1).expandtabs(4))
                ordered = bool(re.match(r"^\d", m.group(2)))
                items.append((indent, ordered, m.group(3)))
                i += 1
            out.append(("list", items))
            continue

        if stripped.startswith(">"):
            flush()
            quote = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append(("quote", " ".join(quote)))
            continue

        if stripped == "":
            flush()
            i += 1
            continue

        para.append(stripped)
        i += 1

    flush()
    return out


def md_to_html(text: str) -> str:
    out = []
    for tok in md_tokens(text):
        if tok[0] == "para":
            out.append("<p>" + inline_md(tok[1]) + "</p>")
        elif tok[0] == "code":
            cls = f' data-lang="{esc(tok[1])}"' if tok[1] else ""
            out.append(f'<pre class="code-block"{cls}><code>' + esc(tok[2]) + "</code></pre>")
        elif tok[0] == "heading":
            out.append(f"<h{tok[1] + 1}>{inline_md(tok[2])}</h{tok[1] + 1}>")
        elif tok[0] == "hr":
            out.append("<hr>")
        elif tok[0] == "table":
            header, rows = tok[1], tok[2]
            tbl = ['<div class="table-wrap"><table><thead><tr>']
            tbl += [f"<th>{inline_md(c)}</th>" for c in header]
            tbl.append("</tr></thead><tbody>")
            for r in rows:
                tbl.append("<tr>" + "".join(f"<td>{inline_md(c)}</td>" for c in r) + "</tr>")
            tbl.append("</tbody></table></div>")
            out.append("".join(tbl))
        elif tok[0] == "list":
            # _render_list stops at a marker-type switch or a dedent below its
            # starting indent; loop until every item is consumed, or a list
            # that switches from bullets to numbers loses its tail.
            items, i = tok[1], 0
            parts = []
            while i < len(items):
                listing, j = _render_list(items, i)
                parts.append(listing)
                i = j if j > i else i + 1
            out.append("".join(parts))
        elif tok[0] == "quote":
            out.append("<blockquote>" + inline_md(tok[1]) + "</blockquote>")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Tool-call one-liners
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Human turns are reproduced verbatim.
#
# A user message is typed text and pastes -- console output, tracebacks, log
# lines, columnar benchmark results -- not authored markdown. v2.0 ran it through
# md_to_html, which joined consecutive lines into run-on paragraphs and turned a
# traceback's dashed separator into an <hr>: a pasted benchmark table came out
# reading like prose, indistinguishable from Claude's own writing. Nothing is
# interpreted here now; only bare URLs become links.
#
# The monospace switch is presentation only -- it decides whether a paste's
# columns line up, never what the text says -- so a wrong guess costs alignment
# and nothing else.
# ---------------------------------------------------------------------------

URL_RE = re.compile(r"(https?://[^\s<>\"')]*[^\s<>\"')\.,;:!?])")
_CONSOLE_RE = re.compile(
    r"(Traceback \(most recent call last\)|^\s*File \"|^\s*at [\w.$]+\(|^\s*\$ |^\s*> |^PS [A-Z]:|"
    r"^\s*(Cell In\[|-{3,}>|\w+Error\b|\w+Exception\b))")


def looks_columnar(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 3:
        return False
    if any(_CONSOLE_RE.search(ln) for ln in lines):
        return True
    aligned = sum(1 for ln in lines
                  if re.search(r"\S {2,}\S", ln) or ln.startswith(("  ", "\t", "|")))
    return aligned >= max(2, len(lines) // 3)


def human_html(text: str) -> str:
    # Link on the raw text and escape each piece afterwards: escaping first
    # turns a trailing apostrophe into &#x27; and the URL swallows it.
    parts = []
    for i, piece in enumerate(URL_RE.split(text)):
        if i % 2:
            parts.append(f'<a href="{esc(piece)}" target="_blank" rel="noopener">{esc(piece)}</a>')
        else:
            parts.append(esc(piece))
    body = "".join(parts)
    cls = "raw mono" if looks_columnar(text) else "raw"
    return f'<div class="{cls}">{body}</div>'


def truncate(s: str, n: int = 100) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def shorten(text: str, width: int = 72) -> str:
    """One-line, bounded label for a box title.

    A tcolorbox title does not wrap: a PowerShell call whose label is the whole
    command ran off the right edge of the page on 95 blocks of one archive.
    Newlines are collapsed first, because a title spanning lines breaks the box.
    """
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[:width - 3].rstrip() + "..."


def pretty_tool_input(raw: str) -> str:
    """Render a tool call's arguments so a human can read them.

    json.dumps keeps a multi-line string on one line with its newlines written
    as \n, so a Write call carrying a whole source file arrives as a single
    escaped string thousands of characters long -- pages of unreadable wrapping
    in any page-based format. Long or multi-line values are broken out as
    indented blocks instead, with the real line breaks restored.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw
    if not isinstance(data, dict):
        return raw
    out = []
    for key, val in data.items():
        if isinstance(val, str):
            text = val
        elif isinstance(val, (dict, list)):
            text = json.dumps(val, indent=2, ensure_ascii=False)
        else:
            text = json.dumps(val, ensure_ascii=False)
        if "\n" in text or len(text) > 88:
            out.append(f"{key}:")
            out.extend("    " + ln for ln in text.replace("\r\n", "\n").split("\n"))
        else:
            out.append(f"{key}: {text}")
    return "\n".join(out)


def describe_tool(name: str, inp: dict) -> tuple[str, str]:
    inp = inp or {}
    simple = {
        "Bash": "command", "PowerShell": "command", "Read": "file_path",
        "Write": "file_path", "Edit": "file_path", "NotebookEdit": "notebook_path",
        "Grep": "pattern", "Glob": "pattern", "WebSearch": "query",
        "WebFetch": "url", "ToolSearch": "query", "Skill": "skill",
        "Agent": "description", "Task": "description", "ScheduleWakeup": "reason",
        "Artifact": "file_path", "SendMessage": "message", "Monitor": "command",
        "CronCreate": "prompt", "TaskOutput": "task_id", "TaskStop": "task_id",
        "SendUserFile": "files",
    }
    if name in simple:
        v = inp.get(simple[name], "")
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        if name == "Artifact" and not v:
            v = inp.get("action", "publish")
        return name, truncate(v)
    if name == "AskUserQuestion":
        qs = inp.get("questions") or []
        return name, truncate("; ".join(q.get("question", "") for q in qs))
    if name == "ReportFindings":
        return name, f"{len(inp.get('findings') or [])} finding(s)"
    if name == "TodoWrite":
        return name, f"{len(inp.get('todos') or [])} item(s)"
    if name.startswith("mcp__"):
        parts = name.split("__")
        short = parts[-1]
        server = parts[1] if len(parts) > 2 else ""
        detail = (inp.get("url") or inp.get("query") or inp.get("text")
                  or inp.get("prompt") or inp.get("action") or "")
        if not detail and inp:
            detail = json.dumps(inp)[:160]
        label = f"{server}/{short}" if server else short
        return label, truncate(detail)
    return name, truncate(json.dumps(inp, ensure_ascii=False)[:200])


# ---------------------------------------------------------------------------
# Human vs injected classification.
#
# Authoritative signals, in order:
#   1. record.origin.kind          -> "human" | "task-notification" | ...
#   2. record.promptSource         -> "typed" | "suggestion_accepted" | "system"
#   3. record.isCompactSummary     -> compaction continuation blob
#   4. text markers (older records written before those fields existed)
#   5. a ScheduleWakeup prompt seen earlier in this same session
#
# (5) is what closes v1's documented "known gap": the archiver now remembers
# what the assistant actually scheduled, so a wakeup prompt firing back as a
# user turn is recognised without any adjacency guessing.
# ---------------------------------------------------------------------------

TEXT_MARKERS = (
    ("<task-notification>",           "Background task notification"),
    ("[SYSTEM NOTIFICATION",          "Background task notification"),
    ("[Your previous response had no visible output", "Harness nudge"),
    ("<command-name>",                "Local slash command"),
    ("<local-command-stdout>",        "Local command output"),
    ("<local-command-caveat>",        "Local command caveat"),
    ("<user-prompt-submit-hook>",     "Prompt-submit hook"),
    ("This session is being continued from a previous conversation",
                                      "Context compaction summary"),
)

# Older records predate promptSource/origin, and a few injected shapes are
# templated rather than prefixed. These were derived by auditing every record
# the field-based signals left unclassified.
REGEX_MARKERS = (
    (re.compile(r"^\[\d+ prior /loop wakeups? found nothing actionable"), "Loop heartbeat"),
    (re.compile(r"^Skill /\S+ is already loaded above"),                  "Skill already loaded"),
    (re.compile(r"^\[Request interrupted"),                               "Interrupted by user"),
    (re.compile(r"^\[Image: original \d+x\d+"),                           "Image scaling note"),
)


def classify_user_string(rec: dict, text: str, scheduled_prompts: set[str]) -> tuple[str, str, str]:
    """-> (kind, badge, evidence). kind is 'human' or 'system'."""
    if rec.get("isCompactSummary"):
        return "system", "Context compaction summary", "isCompactSummary"

    origin = rec.get("origin")
    if isinstance(origin, dict) and origin.get("kind"):
        kind = origin["kind"]
        if kind == "human":
            return "human", "", "origin.kind=human"
        if kind == "task-notification":
            return "system", "Background task notification", "origin.kind=task-notification"
        return "system", kind.replace("-", " ").capitalize(), f"origin.kind={kind}"

    src = rec.get("promptSource")
    if src in ("typed", "suggestion_accepted"):
        return "human", "", f"promptSource={src}"
    if src == "system":
        for marker, badge in TEXT_MARKERS:
            if text.startswith(marker) or marker in text[:200]:
                return "system", badge, f"promptSource=system + {marker}"
        return "system", "Harness-injected prompt", "promptSource=system"

    for marker, badge in TEXT_MARKERS:
        if text.startswith(marker) or marker in text[:200]:
            return "system", badge, f"text marker {marker}"

    for rx, badge in REGEX_MARKERS:
        if rx.match(text):
            return "system", badge, f"pattern {rx.pattern[:34]}"

    norm = " ".join(text.split())
    for prompt in scheduled_prompts:
        if norm and norm == " ".join(prompt.split()):
            return "system", "Scheduled continuation", "matches a ScheduleWakeup prompt"

    return "human", "", "default (no promptSource/origin on this record)"


# ---------------------------------------------------------------------------
# Session discovery + chain resolution
# ---------------------------------------------------------------------------

class SessionFile:
    __slots__ = ("sid", "path", "uuids", "first", "last", "records", "title",
                 "subagents", "source", "conv_uuids")

    def __init__(self, sid, path, uuids, first, last, records, title, conv_uuids=None):
        self.sid, self.path = sid, path
        self.uuids, self.first, self.last = uuids, first, last
        self.records, self.title = records, title
        self.subagents = 0          # subagent transcripts filed under this session
        self.source = "claude-code"  # or "cowork" (Claude Desktop local agent)
        # The exchanges themselves: assistant records and typed prompts. A
        # resume after /compact carries these forward but not the old file's
        # compaction tail, so continuation-vs-fork is judged on them alone.
        self.conv_uuids = conv_uuids if conv_uuids is not None else set(uuids)


def _is_conversation_record(obj: dict) -> bool:
    rtype = obj.get("type")
    if rtype == "assistant":
        return True
    if rtype != "user" or obj.get("isCompactSummary"):
        return False
    msg = obj.get("message") or {}
    if not isinstance(msg.get("content"), str):
        return False                      # tool results, injected blocks
    origin = obj.get("origin")
    if isinstance(origin, dict) and origin.get("kind"):
        return origin["kind"] == "human"
    src = obj.get("promptSource")
    if src:
        return src in ("typed", "suggestion_accepted")
    return not msg["content"].lstrip().startswith("<")   # older records: markers are injected


def scan_sessions(root: Path) -> dict[str, SessionFile]:
    """Sessions only.

    A subagent's transcript lives at <project>/<session-id>/subagents/agent-*.jsonl.
    It is a *part* of its parent session, not a conversation of its own, so it is
    counted against the parent rather than listed as a session -- globbing **/*.jsonl
    blindly reported 178 "sessions" on this machine when there were 40.
    """
    found: dict[str, SessionFile] = {}
    subagents: Counter = Counter()
    for path in sorted(root.glob("**/*.jsonl")):
        if path.name == "audit.jsonl":     # cowork bookkeeping, not a session
            continue
        if "subagents" in path.parts:
            i = path.parts.index("subagents")
            if i:
                subagents[path.parts[i - 1]] += 1
            continue
        uuids: set[str] = set()
        conv: set[str] = set()
        first = last = None
        count = 0
        title = None
        try:
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    count += 1
                    u = obj.get("uuid")
                    if u:
                        uuids.add(u)
                        if _is_conversation_record(obj):
                            conv.add(u)
                    ts = obj.get("timestamp")
                    if ts:
                        if first is None or ts < first:
                            first = ts
                        if last is None or ts > last:
                            last = ts
                    if obj.get("type") == "ai-title" and obj.get("aiTitle"):
                        title = obj["aiTitle"]
        except OSError:
            continue
        found[path.stem] = SessionFile(path.stem, path, uuids, first, last, count, title, conv)
    for sid, n in subagents.items():
        if sid in found:
            found[sid].subagents = n
    return found


def default_cowork_root() -> Path:
    """Where Claude Desktop's cowork (local agent mode) keeps its sessions.

    Same record schema, same <...>/.claude/projects/<proj>/<sid>.jsonl layout,
    different base directory per platform."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "Claude" / "local-agent-mode-sessions"
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support" / "Claude"
                / "local-agent-mode-sessions")
    return Path.home() / ".config" / "Claude" / "local-agent-mode-sessions"


def scan_all_sessions(projects_root: Path, cowork_root: Path | None) -> dict[str, SessionFile]:
    """Claude Code sessions, plus cowork sessions when that root exists.

    Session ids are uuids, so a cross-source collision is not expected; if one
    ever happens the Claude Code file wins and the clash is reported."""
    sessions = scan_sessions(projects_root)
    if cowork_root and cowork_root.is_dir():
        for sid, info in scan_sessions(cowork_root).items():
            info.source = "cowork"
            if sid in sessions:
                print(f"note: session {sid} exists in both {projects_root} and "
                      f"{cowork_root}; using the Claude Code copy", file=sys.stderr)
                continue
            sessions[sid] = info
    return sessions


def resolve_chain(sid: str, sessions: dict[str, SessionFile]) -> tuple[str, list[dict]]:
    """Find the most complete file sharing this session's history.

    A resumed session (or one bridged to web/mobile via /remote-control) is
    written to a *new* .jsonl that repeats the earlier records. Archiving the
    id the user happens to name can therefore capture half a conversation and
    label it with the wrong id -- which is exactly what happened to the v1
    archive of 3c2a527b (its file held 6eb46cd7, a 256-record superset).
    """
    base = sessions[sid]
    related: list[dict] = []
    best = sid
    for other, info in sessions.items():
        if other == sid or not info.uuids or not base.uuids:
            continue
        shared = len(base.uuids & info.uuids)
        if not shared:
            continue
        overlap = shared / min(len(base.uuids), len(info.uuids))
        if overlap < 0.5:
            continue
        # A continuation can drop bookkeeping: a stray bridge_status record, an
        # empty thinking block, or -- after /compact -- the whole compaction
        # tail (attachments, the boundary, the summary; 18 records on one real
        # pair). Strict set containment mislabels those a "fork". So the
        # judgement is made on the *exchanges*: a file that carries every
        # prompt and response of this one (give or take a couple) and goes on
        # is the same conversation continued; one missing exchanges diverged.
        dropped = len(base.uuids - info.uuids)
        base_conv = getattr(base, "conv_uuids", base.uuids)
        info_conv = getattr(info, "conv_uuids", info.uuids)
        dropped_conv = len(base_conv - info.uuids)
        tolerance = max(2, len(base_conv) // 100)
        if dropped == 0 or (dropped_conv <= tolerance and len(info_conv) > len(base_conv)):
            rel = "superset"
        elif base.uuids >= info.uuids:
            rel = "subset"
        else:
            rel = "fork"
        related.append({
            "session_id": other, "shared": shared, "records": info.records,
            "own_uuids": len(info.uuids), "relation": rel, "dropped": dropped,
        })
        # Only a superset is the same conversation continued. A fork shares
        # history but then diverges: archiving it in place of the requested id
        # would silently swap in a different conversation, however large.
        # Compared on exchanges, not raw uuids: the old file's compaction tail
        # can make it the *larger* file while holding less conversation.
        best_conv = getattr(sessions[best], "conv_uuids", sessions[best].uuids)
        if rel == "superset" and len(info_conv) > len(best_conv):
            best = other
    related.sort(key=lambda r: -r["own_uuids"])
    return best, related


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_ts(s: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


class Transcript:
    def __init__(self):
        self.turns: list[dict] = []
        self.counts = Counter()
        self.record_types = Counter()
        self.rendered_types = Counter()
        self.counted_only = Counter()
        self.blocks = Counter()
        self.models = Counter()
        self.usage_by_model: dict[str, Counter] = defaultdict(Counter)
        self.timestamps: list[str] = []
        self.turn_durations_ms = 0
        self.turn_duration_records = 0
        self.version = None
        self.cwd = None
        self.git_branch = None
        self.title_hint = None
        self.typed_prompts: list[str] = []
        self.scheduled_prompts: set[str] = set()
        self.unresolved_tools = 0
        self.classification = Counter()
        self.bridges: list[str] = []
        self.compactions: list[dict] = []
        self.effort = Counter()
        self.skills = Counter()
        self.mcp_servers = Counter()
        self.disposition = Counter()   # per-record: rendered / folded / counted
        self.empty_thinking = 0
        # cost-state snapshots keyed by process startTime (ms): Claude Code
        # restarts its meter on every resume, so one session has many runs.
        self.cost_states: dict[int, dict] = {}


def parse_transcript(path: Path, max_tool_output: int) -> Transcript:
    t = Transcript()
    with path.open(encoding="utf-8") as fh:
        objs = []
        for line in fh:
            if line.strip():
                try:
                    objs.append(json.loads(line))
                except json.JSONDecodeError:
                    # A line the parser cannot even read is still a line of the
                    # source. It enters the record count and the disposition so
                    # the fidelity report shows it -- "no silent drops" must
                    # cover corruption, not just record classes.
                    t.record_types["(unparseable line)"] += 1
                    t.counted_only["unparseable line (invalid JSON)"] += 1
                    t.disposition["counted"] += 1

    # Pass 1: collect ScheduleWakeup prompts so a firing wakeup can be
    # recognised later even on records with no promptSource field.
    for obj in objs:
        if obj.get("type") != "assistant":
            continue
        for b in ((obj.get("message") or {}).get("content") or []):
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "ScheduleWakeup":
                p = (b.get("input") or {}).get("prompt")
                if isinstance(p, str) and p.strip():
                    t.scheduled_prompts.add(p.strip())

    tool_index: dict[str, dict] = {}
    seen_requests: set[str] = set()

    for obj in objs:
        rtype = obj.get("type")
        t.record_types[rtype] += 1
        ts = obj.get("timestamp")
        if ts:
            t.timestamps.append(ts)
        if obj.get("version"):
            t.version = obj["version"]
        if obj.get("cwd"):
            t.cwd = obj["cwd"]
        if obj.get("gitBranch"):
            t.git_branch = obj["gitBranch"]
        if rtype == "ai-title" and obj.get("aiTitle"):
            t.title_hint = obj["aiTitle"]
        if rtype == "last-prompt" and obj.get("lastPrompt"):
            t.typed_prompts.append(obj["lastPrompt"])
        if rtype == "bridge-session" and obj.get("bridgeSessionId"):
            if obj["bridgeSessionId"] not in t.bridges:
                t.bridges.append(obj["bridgeSessionId"])

        # ---- assistant ------------------------------------------------
        if rtype == "assistant":
            turns_before = len(t.turns)
            msg = obj.get("message") or {}
            model = msg.get("model") or "unknown"
            t.models[model] += 1
            if obj.get("effort"):
                t.effort[obj["effort"]] += 1
            if obj.get("attributionSkill"):
                t.skills[obj["attributionSkill"]] += 1
            if obj.get("attributionMcpServer"):
                t.mcp_servers[obj["attributionMcpServer"]] += 1

            rid = obj.get("requestId") or msg.get("id")
            if rid and rid not in seen_requests:
                seen_requests.add(rid)
                u = msg.get("usage") or {}
                agg = t.usage_by_model[model]
                agg["requests"] += 1
                agg["input"] += u.get("input_tokens", 0) or 0
                agg["output"] += u.get("output_tokens", 0) or 0
                agg["cache_read"] += u.get("cache_read_input_tokens", 0) or 0
                cc = u.get("cache_creation") or {}
                w5 = cc.get("ephemeral_5m_input_tokens")
                w1h = cc.get("ephemeral_1h_input_tokens")
                if w5 is None and w1h is None:
                    agg["cache_write_5m"] += u.get("cache_creation_input_tokens", 0) or 0
                else:
                    agg["cache_write_5m"] += w5 or 0
                    agg["cache_write_1h"] += w1h or 0
            elif not rid:
                t.counts["assistant_records_without_request_id"] += 1

            content = msg.get("content")
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            for c in content or []:
                if not isinstance(c, dict):
                    continue
                ctype = c.get("type")
                t.blocks[ctype] += 1
                if ctype == "text":
                    txt = c.get("text", "")
                    if txt.strip():
                        t.turns.append({
                            "kind": "assistant", "ts": ts, "model": model,
                            "html": md_to_html(txt), "text": txt,
                            "sidechain": bool(obj.get("isSidechain")),
                        })
                        t.rendered_types["assistant text"] += 1
                    else:
                        t.counted_only["empty assistant text block"] += 1
                elif ctype == "thinking":
                    txt = c.get("thinking", "")
                    if txt.strip():
                        t.turns.append({
                            "kind": "thinking", "ts": ts, "model": model,
                            "html": md_to_html(txt), "text": txt,
                        })
                        t.rendered_types["thinking"] += 1
                    else:
                        # display:"omitted" -- the block exists, the text never
                        # reaches the transcript. Claude Code runs this way, so
                        # in practice every thinking block is empty: the archive
                        # can show *that* Claude thought, never what it thought.
                        t.empty_thinking += 1
                        t.counted_only["thinking block with no text (display=omitted)"] += 1
                elif ctype == "redacted_thinking":
                    t.turns.append({
                        "kind": "thinking", "ts": ts, "model": model,
                        "html": "<p><em>Redacted thinking (encrypted by the API).</em></p>",
                        "text": "", "redacted": True,
                    })
                    t.rendered_types["redacted thinking"] += 1
                elif ctype == "tool_use":
                    name = c.get("name", "tool")
                    inp = c.get("input", {})
                    chip, label = describe_tool(name, inp)
                    turn = {
                        "kind": "tool", "ts": ts, "chip": chip, "label": label,
                        "tool_name": name,
                        "input": json.dumps(inp, indent=2, ensure_ascii=False),
                        "output_text": None, "output_images": [],
                        "is_error": False, "resolved": False,
                        "sidechain": bool(obj.get("isSidechain")),
                    }
                    tool_index[c.get("id")] = turn
                    t.turns.append(turn)
                    t.rendered_types["tool call"] += 1
                else:
                    t.turns.append({
                        "kind": "raw_block", "ts": ts,
                        "badge": f"assistant block: {ctype}",
                        "text": json.dumps(c, indent=2, ensure_ascii=False)[:4000],
                    })
                    t.rendered_types[f"assistant block ({ctype})"] += 1
            t.disposition["rendered" if len(t.turns) > turns_before else "counted"] += 1
            continue

        # ---- user -----------------------------------------------------
        if rtype == "user":
            turns_before = len(t.turns)
            folded = False
            msg = obj.get("message") or {}
            content = msg.get("content")

            if isinstance(content, str):
                text = content.strip()
                if not text:
                    t.counted_only["empty user record"] += 1
                    t.disposition["counted"] += 1
                    continue
                kind, badge, evidence = classify_user_string(obj, text, t.scheduled_prompts)
                t.classification[evidence] += 1
                if kind == "human":
                    t.turns.append({"kind": "human", "ts": ts, "text": text,
                                    "html": human_html(text)})
                    t.rendered_types["human turn"] += 1
                else:
                    body = text
                    if badge == "Background task notification":
                        m = re.search(r"<task-notification>.*?</task-notification>", text, re.S)
                        body = m.group(0) if m else text
                    t.turns.append({"kind": "system", "ts": ts, "badge": badge,
                                    "text": body, "evidence": evidence})
                    t.rendered_types[f"system turn ({badge})"] += 1
                t.disposition["rendered"] += 1
                continue

            if isinstance(content, list):
                # A text block in list content is normally harness text riding
                # beside a tool result. Only positive provenance (origin.kind or
                # promptSource on the record) makes it a human prompt -- the
                # shape Claude Code uses when text and an image are typed together.
                origin_kind = (obj.get("origin") or {}).get("kind") \
                    if isinstance(obj.get("origin"), dict) else None
                typed_here = (origin_kind == "human"
                              or obj.get("promptSource") in ("typed", "suggestion_accepted"))
                for c in content:
                    if not isinstance(c, dict):
                        continue
                    ctype = c.get("type")
                    t.blocks[f"user:{ctype}"] += 1
                    if ctype == "text":
                        txt = (c.get("text") or "").strip()
                        if txt and typed_here:
                            evidence = ("origin.kind=human" if origin_kind == "human"
                                        else f"promptSource={obj.get('promptSource')}")
                            t.classification[evidence + " (list content)"] += 1
                            t.turns.append({"kind": "human", "ts": ts, "text": txt,
                                            "html": human_html(txt)})
                            t.rendered_types["human turn"] += 1
                        elif txt:
                            t.turns.append({
                                "kind": "system", "ts": ts,
                                "badge": "Instructions injected into the turn",
                                "text": txt, "evidence": "user content-block text",
                            })
                            t.rendered_types["system turn (injected instructions)"] += 1
                    elif ctype == "image":
                        src = c.get("source") or {}
                        if src.get("data"):
                            t.turns.append({
                                "kind": "user_image", "ts": ts,
                                "media": src.get("media_type", "image/png"),
                                "data": src["data"],
                            })
                            t.rendered_types["pasted image"] += 1
                    elif ctype == "tool_result":
                        turn = tool_index.get(c.get("tool_use_id"))
                        if not turn:
                            t.counted_only["tool_result with no matching tool_use"] += 1
                            continue
                        parts: list[str] = []
                        cc = c.get("content")
                        if isinstance(cc, str):
                            parts.append(cc)
                        elif isinstance(cc, list):
                            for x in cc:
                                if not isinstance(x, dict):
                                    continue
                                xt = x.get("type")
                                if xt == "text":
                                    parts.append(x.get("text", ""))
                                elif xt == "image":
                                    isrc = x.get("source") or {}
                                    if isrc.get("data"):
                                        turn["output_images"].append(
                                            (isrc.get("media_type", "image/png"), isrc["data"]))
                                elif xt == "tool_result":
                                    inner = x.get("content")
                                    if isinstance(inner, str):
                                        parts.append(inner)
                                elif xt == "tool_reference":
                                    parts.append(f"[tool loaded: {x.get('tool_name', '?')}]")
                                else:
                                    parts.append(json.dumps(x, ensure_ascii=False)[:2000])
                        elif cc is not None:
                            parts.append(json.dumps(cc, ensure_ascii=False))
                        text = "\n".join(p for p in parts if p)
                        if max_tool_output and len(text) > max_tool_output:
                            head = text[: int(max_tool_output * 0.75)]
                            tail = text[-int(max_tool_output * 0.25):]
                            elided = len(text) - len(head) - len(tail)
                            text = (f"{head}\n\n… [{elided:,} characters elided by "
                                    f"--max-tool-output; re-run with --full for everything] …\n\n{tail}")
                            turn["elided"] = elided
                        turn["output_text"] = text
                        turn["is_error"] = bool(c.get("is_error"))
                        turn["resolved"] = True
                        folded = True
                        # The record carrying an Agent tool's result names the
                        # spawned agent in a top-level toolUseResult.agentId --
                        # the only durable link between the parent conversation
                        # and <session-id>/subagents/agent-<id>.jsonl.
                        tur = obj.get("toolUseResult")
                        if isinstance(tur, dict) and tur.get("agentId"):
                            turn["agent_id"] = tur["agentId"]
                    else:
                        t.turns.append({
                            "kind": "raw_block", "ts": ts,
                            "badge": f"user block: {ctype}",
                            "text": json.dumps(c, indent=2, ensure_ascii=False)[:4000],
                        })
                        t.rendered_types[f"user block ({ctype})"] += 1
                if len(t.turns) > turns_before:
                    t.disposition["rendered"] += 1
                elif folded:
                    t.disposition["folded"] += 1
                else:
                    t.disposition["counted"] += 1
                continue

            t.counted_only["user record with no content"] += 1
            t.disposition["counted"] += 1
            continue

        # ---- attachment ------------------------------------------------
        if rtype == "attachment":
            att = obj.get("attachment") or {}
            atype = att.get("type", "unknown")
            policy, label = ATTACHMENT_POLICY.get(atype, ("render", atype.replace("_", " ")))
            if policy == "count":
                t.counted_only[f"attachment: {atype}"] += 1
                t.disposition["counted"] += 1
                continue
            t.disposition["rendered"] += 1
            detail, body = summarize_attachment(atype, att)
            t.turns.append({
                "kind": "harness", "ts": ts, "badge": label,
                "detail": detail, "text": body, "atype": atype,
            })
            t.rendered_types[f"harness ({atype})"] += 1
            continue

        # ---- system ----------------------------------------------------
        if rtype == "system":
            sub = obj.get("subtype") or "unknown"
            policy, label = SYSTEM_SUBTYPE_POLICY.get(sub, ("render", sub.replace("_", " ")))
            if sub == "turn_duration":
                t.turn_durations_ms += obj.get("durationMs") or 0
                t.turn_duration_records += 1
                t.counted_only["system: turn_duration (used for duration metric)"] += 1
                t.disposition["counted"] += 1
                continue
            if policy == "count":
                t.counted_only[f"system: {sub}"] += 1
                t.disposition["counted"] += 1
                continue
            t.disposition["rendered"] += 1
            body = obj.get("content")
            if not isinstance(body, str):
                body = json.dumps(body, ensure_ascii=False) if body is not None else ""
            detail = ""
            if sub == "compact_boundary":
                meta = obj.get("compactMetadata") or {}
                pre, post = meta.get("preTokens"), meta.get("postTokens")
                dropped = meta.get("cumulativeDroppedTokens")
                detail = (f"trigger={meta.get('trigger')} "
                          f"{pre:,} → {post:,} tokens" if pre and post else str(meta.get("trigger", "")))
                t.compactions.append({"trigger": meta.get("trigger"), "pre": pre,
                                      "post": post, "dropped": dropped})
                body = body or "Conversation compacted"
            elif sub == "scheduled_task_fire":
                detail = obj.get("cronKind") or ""
            elif sub == "bridge_status":
                detail = obj.get("url") or ""
            t.turns.append({"kind": "system_record", "ts": ts, "badge": label,
                            "detail": detail, "text": body, "subtype": sub})
            t.rendered_types[f"system record ({sub})"] += 1
            continue

        # ---- everything else -------------------------------------------
        t.disposition["counted"] += 1
        if rtype in METADATA_RECORD_TYPES:
            t.counted_only[f"metadata: {rtype}"] += 1
            if rtype == "cost-state":
                # cumulative within a run: the last snapshot per run wins
                key = _cost_state_key(obj)
                if key is not None:
                    t.cost_states[key] = obj
        else:
            t.counted_only[f"unhandled record type: {rtype}"] += 1

    t.unresolved_tools = sum(1 for turn in t.turns
                             if turn["kind"] == "tool" and not turn["resolved"])
    return t


def summarize_attachment(atype: str, att: dict) -> tuple[str, str]:
    """-> (one-line detail, expandable body)."""
    if atype == "hook_success":
        detail = f"{att.get('hookName', '?')} exit={att.get('exitCode')}"
        body = "\n".join(x for x in (att.get("stdout"), att.get("stderr")) if x)
        if att.get("command"):
            body = f"$ {att['command']}\n{body}"
        return detail, body or "(no output)"
    if atype in ("hook_additional_context", "hook_system_message", "skill_listing", "task_reminder"):
        content = att.get("content")
        if isinstance(content, list):
            content = "\n".join(str(x) for x in content)
        extra = ""
        if atype == "skill_listing":
            extra = f"{att.get('skillCount', '?')} skills"
        elif atype in ("hook_additional_context", "hook_system_message"):
            extra = att.get("hookName", "")
        elif atype == "task_reminder":
            extra = f"{att.get('itemCount', 0)} items"
        return extra, str(content or "")
    if atype == "invoked_skills":
        skills = att.get("skills") or []
        names = ", ".join(s.get("name", "?") for s in skills if isinstance(s, dict))
        body = "\n\n".join(
            f"--- {s.get('name')} ({s.get('path')}) ---\n{(s.get('content') or '')[:6000]}"
            for s in skills if isinstance(s, dict))
        return names, body
    if atype in ("nested_memory", "file"):
        content = att.get("content")
        if isinstance(content, dict):
            inner = content.get("file") if isinstance(content.get("file"), dict) else None
            content = (inner or content).get("content", json.dumps(content)[:4000])
        return att.get("displayPath") or att.get("filename", ""), str(content or "")[:20000]
    if atype == "edited_text_file":
        return att.get("displayPath") or att.get("filename", ""), str(att.get("snippet") or "")
    if atype == "compact_file_reference":
        return att.get("displayPath") or att.get("filename", ""), ""
    if atype == "read_truncation_notice":
        return "", str(att.get("banner") or "")
    if atype == "deferred_tools_delta":
        added, removed = att.get("addedNames") or [], att.get("removedNames") or []
        detail = f"+{len(added)} / -{len(removed)} tools"
        return detail, "added: " + ", ".join(added) + ("\nremoved: " + ", ".join(removed) if removed else "")
    if atype == "agent_listing_delta":
        added = att.get("addedTypes") or []
        return f"+{len(added)} agents", "\n".join(att.get("addedLines") or [])
    if atype == "mcp_instructions_delta":
        names = att.get("addedNames") or []
        return ", ".join(names), "\n\n".join(att.get("addedBlocks") or [])
    if atype == "command_permissions":
        tools = att.get("allowedTools") or []
        return f"{len(tools)} allowed", ", ".join(tools)
    if atype == "queued_command":
        return att.get("commandMode", ""), str(att.get("prompt") or "")
    if atype == "date_change":
        return str(att.get("newDate", "")), ""
    return "", json.dumps(att, indent=2, ensure_ascii=False)[:8000]


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_dur_ms(ms: int) -> str:
    total = int(ms // 1000)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def fmt_local(dt: datetime.datetime) -> str:
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def fmt_utc(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def tokens(n: int) -> str:
    return f"{n:,}"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

# Claude Code >= 2.1.9x writes `cost-state`: its own cost meter, per process.
# Every `claude --resume` starts a new counter (new startTime), and runs made
# before the record existed wrote none -- so the reported figure is the sum of
# the last snapshot of each run, and it can cover only part of a session.
COVERAGE_SLACK_S = 60


def _cost_state_key(obj: dict) -> int | None:
    """The run a cost-state snapshot belongs to, or None if the record is
    unusable (missing, non-numeric or non-finite startTime). A malformed
    bookkeeping record must never abort an export."""
    st = obj.get("startTime")
    if isinstance(st, bool) or not isinstance(st, (int, float)):
        return None
    if isinstance(st, float) and not math.isfinite(st):
        return None
    return int(st)


def _num(v, cast=float):
    try:
        out = cast(v or 0)
    except (TypeError, ValueError):
        return cast(0)
    return out if math.isfinite(float(out)) else cast(0)


def cost_states_of(path: Path) -> dict[int, dict]:
    """Only the cost-state snapshots of a transcript file, last per run.

    A resumed session's continuation file repeats the conversation records
    but not the earlier process's cost-state, so build() gathers the meter
    from every file in the chain. This reads just those lines, cheaply."""
    found: dict[int, dict] = {}
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if '"cost-state"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "cost-state":
                    continue
                key = _cost_state_key(obj)
                if key is not None:
                    found[key] = obj
    except OSError:
        pass
    return found


def reported_cost(t: Transcript, started: datetime.datetime | None = None) -> dict | None:
    if not t.cost_states:
        return None
    runs = [t.cost_states[k] for k in sorted(t.cost_states)]
    by_model: Counter = Counter()
    for r in runs:
        mu_all = r.get("modelUsage")
        if not isinstance(mu_all, dict):
            continue
        for model, mu in mu_all.items():
            if isinstance(mu, dict):
                by_model[str(model)] += _num(mu.get("costUSD"))
    first_start = datetime.datetime.fromtimestamp(min(t.cost_states) / 1000,
                                                  datetime.timezone.utc)
    partial = bool(started is not None
                   and (first_start - started).total_seconds() > COVERAGE_SLACK_S)
    return {
        "usd": sum(_num(r.get("totalCostUSD")) for r in runs),
        "runs": len(runs),
        "first_start": first_start,
        "partial": partial,
        "unknown_model_cost": any(r.get("hasUnknownModelCost") for r in runs),
        "lines_added": sum(_num(r.get("totalLinesAdded"), int) for r in runs),
        "lines_removed": sum(_num(r.get("totalLinesRemoved"), int) for r in runs),
        "by_model": dict(by_model),
    }


def reported_cost_note(rc: dict | None) -> str:
    """One plain sentence for the text, Markdown and LaTeX formats -- the same
    facts the HTML usage note states, so no format is silent about coverage."""
    if not rc:
        return ""
    s = (f"Reported cost: ${rc['usd']:,.2f} reported by Claude Code's own meter "
         f"(cost-state records) over {rc['runs']} run(s) of this session")
    if rc["lines_added"] or rc["lines_removed"]:
        s += f"; {rc['lines_added']:,} lines added, {rc['lines_removed']:,} removed by tools"
    if rc["partial"]:
        s += (f". This session began before its first metered run "
              f"({fmt_local(rc['first_start'])}); spend before that is not covered, "
              "so the list-price figure is the estimate for the whole session.")
    else:
        s += ". The meter covers the whole session."
    if rc["unknown_model_cost"]:
        s += " Claude Code flagged a model it could not price; the reported total is a floor."
    return s


def usage_table(t: Transcript, on: datetime.date,
                rc: dict | None = None) -> tuple[str, dict]:
    rows = []
    totals = Counter()
    total_cost = 0.0
    unpriced = []
    for model, agg in sorted(t.usage_by_model.items(), key=lambda kv: -kv[1]["output"]):
        rates = model_rates(model, on)
        for k, v in agg.items():
            totals[k] += v
        if rates:
            in_rate, out_rate = rates
            cost = (agg["input"] * in_rate
                    + agg["output"] * out_rate
                    + agg["cache_read"] * in_rate * CACHE_READ_MULTIPLIER
                    + agg["cache_write_5m"] * in_rate * CACHE_WRITE_MULTIPLIER["5m"]
                    + agg["cache_write_1h"] * in_rate * CACHE_WRITE_MULTIPLIER["1h"]) / 1_000_000
            total_cost += cost
            cost_cell = f"${cost:,.2f}"
        else:
            unpriced.append(model)
            cost_cell = "<span class=\"muted\">no list price</span>"
        rep_cell = ""
        if rc:
            rv = rc["by_model"].get(model)
            rep_cell = ("<td class=num>" + (f"${rv:,.2f}" if rv is not None
                                            else '<span class="muted">&mdash;</span>') + "</td>")
        rows.append(
            "<tr><td><code>{m}</code></td><td class=num>{req}</td><td class=num>{inp}</td>"
            "<td class=num>{out}</td><td class=num>{cr}</td><td class=num>{cw}</td>"
            "<td class=num>{cost}</td>{rep}</tr>".format(
                m=esc(model), req=tokens(agg["requests"]), inp=tokens(agg["input"]),
                out=tokens(agg["output"]), cr=tokens(agg["cache_read"]),
                cw=tokens(agg["cache_write_5m"] + agg["cache_write_1h"]), cost=cost_cell,
                rep=rep_cell))
    if rc:
        # models Claude Code priced that never produced a rendered response
        for model in sorted(set(rc["by_model"]) - set(t.usage_by_model)):
            rows.append(f"<tr><td><code>{esc(model)}</code></td>"
                        + '<td class=num>&mdash;</td>' * 5
                        + '<td class=num><span class="muted">&mdash;</span></td>'
                        + f'<td class=num>${rc["by_model"][model]:,.2f}</td></tr>')
    foot = (
        "<tr class=total><td>total</td><td class=num>{req}</td><td class=num>{inp}</td>"
        "<td class=num>{out}</td><td class=num>{cr}</td><td class=num>{cw}</td>"
        "<td class=num>${cost:,.2f}</td>{rep}</tr>".format(
            req=tokens(totals["requests"]), inp=tokens(totals["input"]),
            out=tokens(totals["output"]), cr=tokens(totals["cache_read"]),
            cw=tokens(totals["cache_write_5m"] + totals["cache_write_1h"]),
            cost=total_cost,
            rep=(f'<td class=num>${rc["usd"]:,.2f}</td>' if rc else "")))
    table = (
        '<div class="table-wrap"><table class="usage"><thead><tr>'
        "<th>model</th><th>requests</th><th>input</th><th>output</th>"
        "<th>cache read</th><th>cache write</th><th>list cost</th>"
        + ("<th>reported cost</th>" if rc else "")
        + "</tr></thead><tbody>" + "".join(rows) + foot + "</tbody></table></div>")
    note = (
        "<p class=\"muted small\">Usage is deduped per <code>requestId</code> (one API response is "
        "written as several records, each repeating that response's cumulative usage; summing them "
        "over-reports output by ~2.3&times; on a tool-heavy session). Cost is an estimate at public "
        "list rates &mdash; cache reads at 0.1&times; input, 5-minute cache writes at 1.25&times;, "
        "1-hour writes at 2&times; &mdash; not what a subscription bills."
        + (f" No list price on file for: {esc(', '.join(sorted(set(unpriced))))}." if unpriced else "")
        + "</p>")
    if rc:
        note += (
            '<p class="muted small"><b>Reported cost</b> is Claude Code\'s own meter '
            f'(<code>cost-state</code> records): ${rc["usd"]:,.2f} reported by Claude Code over '
            f'{rc["runs"]} run(s) of this session'
            + (f'; {rc["lines_added"]:,} lines added, {rc["lines_removed"]:,} removed by tools'
               if rc["lines_added"] or rc["lines_removed"] else "")
            + '. The meter restarts on every resume and only runs on Claude Code &ge; 2.1.9x write it'
            + (f' &mdash; <b>this session began before its first metered run '
               f'({fmt_local(rc["first_start"])}); spend before that is not covered</b>, so the '
               'list-price estimate is the figure for the whole session.'
               if rc["partial"] else
               ', and here the meter covers the whole session.')
            + (' Claude Code flagged a model it could not price; the reported total is a floor.'
               if rc["unknown_model_cost"] else "")
            + '</p>')
    # A session with no assistant response at all (opened, never answered) leaves
    # `totals` empty; callers index these keys directly, so seed them.
    out = {k: 0 for k in ("requests", "input", "output", "cache_read",
                          "cache_write_5m", "cache_write_1h")}
    out.update(totals)
    out["cost"] = total_cost
    out["reported"] = rc
    return table + note, out


def fidelity_section(t: Transcript, path: Path, archived_at: datetime.datetime,
                     agents: list = (), subagents_on: bool = True) -> str:
    rendered = sum(t.rendered_types.values())
    counted = sum(t.counted_only.values())

    def rows(counter: Counter) -> str:
        return "".join(f"<tr><td>{esc(k)}</td><td class=num>{v:,}</td></tr>"
                       for k, v in sorted(counter.items(), key=lambda kv: -kv[1]))

    total_records = sum(t.record_types.values())
    disp = t.disposition
    reconciles = (disp["rendered"] + disp["folded"] + disp["counted"]) == total_records
    disposition_html = (
        '<div class="table-wrap"><table class="mini"><tbody>'
        f'<tr><td>records that produced one or more turns below</td><td class=num>{disp["rendered"]:,}</td></tr>'
        f'<tr><td>records folded into an earlier turn (tool results)</td><td class=num>{disp["folded"]:,}</td></tr>'
        f'<tr><td>records counted only (no transcript content)</td><td class=num>{disp["counted"]:,}</td></tr>'
        f'<tr class="total"><td>total records in the source</td><td class=num>{total_records:,}</td></tr>'
        "</tbody></table></div>"
        + ("" if reconciles else
           '<p class="callout"><strong>These do not add up</strong> — a record class is escaping '
           'the parser. Treat the transcript below as incomplete.</p>'))

    warn = []
    if t.empty_thinking:
        warn.append(
            f"{t.empty_thinking:,} thinking blocks are present in the source with <em>no text</em>. "
            "Claude Code requests thinking with <code>display: \"omitted\"</code>, so the reasoning "
            "itself never reaches the transcript — this archive can show that Claude thought at a "
            "given point, never what it thought. Nothing was lost in archiving.")
    if t.unresolved_tools:
        warn.append(f"{t.unresolved_tools} tool call(s) have no result in the source "
                    "(still running, or interrupted, when this file was written).")
    typed = len({" ".join(p.split()) for p in t.typed_prompts})
    humans = t.rendered_types.get("human turn", 0)
    if typed and abs(typed - humans) > 2:
        warn.append(f"{humans} human turns rendered vs {typed} distinct prompts in the "
                    "session's own <code>last-prompt</code> index &mdash; worth a look.")
    # Only claim self-archiving when the source is still being written; archiving a
    # finished session from a different session is the common case.
    ends = sorted(parse_ts(x) for x in t.timestamps)
    last_record = ends[-1] if ends else None
    live = bool(last_record) and (archived_at - last_record).total_seconds() < 600
    if last_record is None:
        warn.append("No record in the source carries a timestamp, so when the conversation "
                    "happened cannot be established from this file.")
    elif live:
        warn.append("This archive was written while the session was still active, so records "
                    f"created after {esc(fmt_local(archived_at))} are not in it. Re-run to refresh.")
    else:
        warn.append(f"Snapshot taken {esc(fmt_local(archived_at))}; the source's last record is "
                    f"{esc(fmt_local(last_record))}. Anything written to the session after that "
                    "is not in this file. Re-run to refresh.")

    return f"""
<section class="turn report-turn" id="fidelity">
  <div class="turn-label"><span class="who">Fidelity report</span></div>
  <div class="turn-body report-body">
    <p>Every record in the source, and what happened to it. Nothing is dropped silently:
       a record is either rendered below, folded into an earlier turn, or counted here as
       deliberately not rendered.</p>
    <h4>Record disposition</h4>
    {disposition_html}
    <div class="report-grid">
      <div>
        <h4>Source records by type</h4>
        <div class="table-wrap"><table class="mini"><tbody>{rows(t.record_types)}</tbody></table></div>
        <h4>Content blocks</h4>
        <div class="table-wrap"><table class="mini"><tbody>{rows(t.blocks)}</tbody></table></div>
      </div>
      <div>
        <h4>Rendered ({rendered:,} turns)</h4>
        <div class="table-wrap"><table class="mini"><tbody>{rows(t.rendered_types)}</tbody></table></div>
        <h4>Counted, not rendered ({counted:,})</h4>
        <div class="table-wrap"><table class="mini"><tbody>{rows(t.counted_only)}</tbody></table></div>
      </div>
    </div>
    <h4>Human-vs-injected evidence</h4>
    <p class="muted small">Which signal classified each string-content user record. <code>promptSource</code>
       and <code>origin.kind</code> are authoritative; the rest are fallbacks for older records.</p>
    <div class="table-wrap"><table class="mini"><tbody>{rows(t.classification)}</tbody></table></div>
    {subagent_block(agents, subagents_on)}
    <h4>Caveats</h4>
    <ul>{''.join(f'<li>{w}</li>' for w in warn)}</ul>
    <p class="muted small">Source: <code>{esc(str(path))}</code> &middot;
       archiver v{VERSION}</p>
  </div>
</section>"""


def assign_tags(t: Transcript, prefix: str = "") -> None:
    """Give every prompt and response a citable id: P1, P2, ... / R1, R2, ...

    Sequential within one transcript; subagent transcripts get a prefix
    (A1., A2., ...) so a tag is unique across the whole document and main
    text can say "in prompt P32" or "in response A2.R4" unambiguously."""
    p = r = 0
    for turn in t.turns:
        if turn["kind"] == "human":
            p += 1
            turn["tag"] = f"{prefix}P{p}"
        elif turn["kind"] == "assistant":
            r += 1
            turn["tag"] = f"{prefix}R{r}"


def subagent_block(agents: list, subagents_on: bool) -> str:
    """Fidelity-report table of the session's subagent transcript files.

    Listed whether or not they are rendered: an omitted transcript the report
    does not mention would be exactly the silent drop this tool exists to
    prevent."""
    if not agents:
        return ""
    note = ("Rendered in full in the Subagent transcripts section below."
            if subagents_on else
            "<strong>Not rendered</strong> (--subagents off) — listed here so the "
            "omission is on the record. Their token usage is still counted above.")
    rows = "".join(
        f"<tr><td><code>agent-{esc(aid)}</code></td>"
        f"<td class=num>{sum(at.record_types.values()):,}</td>"
        f"<td class=num>{len(at.turns):,}</td></tr>"
        for aid, _af, at in agents)
    return (f"<h4>Subagent transcripts ({len(agents)})</h4>"
            f'<p class="muted small">{note}</p>'
            '<div class="table-wrap"><table class="mini"><tbody>'
            "<tr><th>file</th><th>records</th><th>turns</th></tr>"
            f"{rows}</tbody></table></div>")


def render_turns(t: Transcript, anchor_prefix: str = "",
                 agent_href: dict | None = None
                 ) -> tuple[list, list[tuple[str, str, str]]]:
    """-> (units, toc): one (html, anchor-or-None) unit per turn, so a caller
    can join them into one page or chunk them across several."""
    body: list[str] = []
    anchors: list = []
    toc: list[tuple[str, str, str]] = []
    counter = 0

    for turn in t.turns:
        kind = turn["kind"]
        cur_anchor = None
        ts_attr = ""
        ts_disp = ""
        if turn.get("ts"):
            dt = parse_ts(turn["ts"])
            ts_disp = fmt_local(dt)
            ts_attr = f' title="{fmt_utc(dt)}"'

        if kind == "human":
            counter += 1
            anchor = f"{anchor_prefix}turn-{counter}"
            cur_anchor = anchor
            tag = turn.get("tag", "")
            tag_html = f' <span class="rtag" id="{esc(tag)}">{esc(tag)}</span>' if tag else ""
            toc.append((anchor, (f"{tag} · " if tag else "") + truncate(turn["text"], 66), "human"))
            body.append(f"""
<section class="turn human-turn" id="{anchor}" data-lane="human">
  <div class="turn-label"><span class="who">Human{tag_html}</span><span class="ts"{ts_attr}>{ts_disp}</span></div>
  <div class="turn-body">{turn["html"]}</div>
</section>""")

        elif kind == "system":
            counter += 1
            anchor = f"{anchor_prefix}turn-{counter}"
            cur_anchor = anchor
            toc.append((anchor, turn["badge"], "system"))
            ev = f'<span class="evidence" title="how this was classified">{esc(turn.get("evidence", ""))}</span>'
            body.append(f"""
<section class="turn system-turn" id="{anchor}" data-lane="system">
  <div class="turn-label"><span class="who">System</span><span class="badge">{esc(turn["badge"])}</span>{ev}<span class="ts"{ts_attr}>{ts_disp}</span></div>
  <div class="turn-body"><details><summary>{esc(truncate(turn["text"], 110))}</summary><pre class="plain">{esc(turn["text"])}</pre></details></div>
</section>""")

        elif kind == "system_record":
            counter += 1
            anchor = f"{anchor_prefix}turn-{counter}"
            cur_anchor = anchor
            label = turn["badge"] + (f" — {turn['detail']}" if turn.get("detail") else "")
            toc.append((anchor, label, "system"))
            body_html = (f'<pre class="plain">{esc(turn["text"])}</pre>' if turn["text"] else "")
            body.append(f"""
<section class="turn event-turn" id="{anchor}" data-lane="system">
  <div class="turn-label"><span class="who">Event</span><span class="badge">{esc(turn["badge"])}</span><span class="evidence">{esc(turn.get("detail", ""))}</span><span class="ts"{ts_attr}>{ts_disp}</span></div>
  <div class="turn-body">{body_html}</div>
</section>""")

        elif kind == "assistant":
            side = ' <span class="badge side">subagent</span>' if turn.get("sidechain") else ""
            tag = turn.get("tag", "")
            tag_html = f' <span class="rtag" id="{esc(tag)}">{esc(tag)}</span>' if tag else ""
            body.append(f"""
<section class="turn assistant-turn" data-lane="assistant">
  <div class="turn-label"><span class="who">Claude{tag_html}</span>{side}<span class="ts"{ts_attr}>{ts_disp}</span></div>
  <div class="turn-body">{turn["html"]}</div>
</section>""")

        elif kind == "thinking":
            body.append(f"""
<section class="turn thinking-turn" data-lane="thinking">
  <details>
    <summary><span class="who">Thinking</span><span class="ts"{ts_attr}>{ts_disp}</span></summary>
    <div class="turn-body">{turn["html"]}</div>
  </details>
</section>""")

        elif kind == "user_image":
            body.append(f"""
<section class="turn human-turn" data-lane="human">
  <div class="turn-label"><span class="who">Human</span><span class="badge">pasted image</span><span class="ts"{ts_attr}>{ts_disp}</span></div>
  <div class="turn-body"><img loading="lazy" src="data:{esc(turn["media"])};base64,{esc(turn["data"])}" alt="pasted image"></div>
</section>""")

        elif kind == "harness":
            detail = f'<span class="evidence">{esc(turn.get("detail", ""))}</span>' if turn.get("detail") else ""
            inner = f'<pre class="plain">{esc(turn["text"])}</pre>' if turn["text"] else "<p class=muted>(no content)</p>"
            body.append(f"""
<section class="turn harness-turn" data-lane="harness">
  <details>
    <summary><span class="chip harness-chip">harness</span> {esc(turn["badge"])} {detail}<span class="ts"{ts_attr}>{ts_disp}</span></summary>
    <div class="io">{inner}</div>
  </details>
</section>""")

        elif kind == "tool":
            classes = "tool-turn"
            if turn["is_error"]:
                classes += " tool-error"
            if not turn["resolved"]:
                classes += " tool-pending"
            side = ' <span class="badge side">subagent</span>' if turn.get("sidechain") else ""
            # Link only to transcripts that are actually on this page; an
            # agent id with no discovered file would be a dead anchor.
            if agent_href and turn.get("agent_id") in agent_href:
                side += (f' <a class="badge side" href="{esc(agent_href[turn["agent_id"]])}">'
                         "transcript &darr;</a>")
            io = [f"""
      <div class="io-block"><div class="io-label">Input</div>
        <pre class="plain">{esc(pretty_tool_input(turn["input"]))}</pre></div>"""]
            if turn["output_text"]:
                lbl = "Output (error)" if turn["is_error"] else "Output"
                extra = ""
                if turn.get("elided"):
                    extra = f' <span class="evidence">{turn["elided"]:,} chars elided</span>'
                io.append(f"""
      <div class="io-block"><div class="io-label">{lbl}{extra}</div>
        <pre class="plain">{esc(turn["output_text"])}</pre></div>""")
            elif turn["resolved"]:
                io.append('<div class="io-block"><div class="io-label">Output</div>'
                          '<p class="muted">(empty result)</p></div>')
            else:
                io.append('<div class="io-block"><div class="io-label">Output</div>'
                          '<p class="muted">No result in the source &mdash; this call was still '
                          'running (or was interrupted) when the transcript was written.</p></div>')
            for media, data in turn["output_images"]:
                io.append(f"""
      <div class="io-block"><div class="io-label">Screenshot</div>
        <img loading="lazy" src="data:{esc(media)};base64,{esc(data)}" alt="tool screenshot"></div>""")
            body.append(f"""
<section class="turn {classes}" data-lane="tool">
  <details>
    <summary><span class="chip tool-chip">{esc(turn["chip"])}</span> <code>{esc(turn["label"])}</code>{side}<span class="ts"{ts_attr}>{ts_disp}</span></summary>
    <div class="io">{''.join(io)}</div>
  </details>
</section>""")

        elif kind == "raw_block":
            body.append(f"""
<section class="turn harness-turn" data-lane="harness">
  <details>
    <summary><span class="chip harness-chip">raw</span> {esc(turn["badge"])}<span class="ts"{ts_attr}>{ts_disp}</span></summary>
    <div class="io"><pre class="plain">{esc(turn["text"])}</pre></div>
  </details>
</section>""")

        while len(anchors) < len(body):
            anchors.append(cur_anchor)

    return list(zip(body, anchors)), toc


def build(session_id: str, title: str, out_path: Path, summary_inner: str,
          projects_root: Path, follow_chain: bool, max_tool_output: int,
          formats: tuple = ("html",), fragment: bool = False,
          tool_output: str = "on", sessions: dict | None = None,
          subagents: str = "on", paginate: int = 0,
          source_kind: str | None = None) -> dict:
    # scan_sessions reads every .jsonl under the root; the caller usually has
    # the scan already, so reuse it rather than reading them all a second time.
    if sessions is None:
        sessions = scan_sessions(projects_root)
    if session_id not in sessions:
        sys.exit(f"No {session_id}.jsonl under {projects_root}")

    requested = session_id
    chain_best, related = resolve_chain(session_id, sessions)
    used = chain_best if follow_chain else session_id
    if follow_chain and used != requested:
        CON.note(f"note: {requested} is continued by {used} "
                 f"({len(sessions[used].uuids):,} conversation records vs "
                 f"{len(sessions[requested].uuids):,}); archiving {used}")

    path = sessions[used].path
    CON.detail(f"parsing {path}")
    t = parse_transcript(path, max_tool_output)
    archived_at = datetime.datetime.now(datetime.timezone.utc)

    # Subagent transcripts live beside the session at
    # <session-id>/subagents/agent-<id>.jsonl, in the same record schema, and
    # share no uuids with the parent file -- they are conversation the parent
    # only points at. Parse them all regardless of the --subagents flag: their
    # usage is real spend either way, and the fidelity report must list the
    # files even when their content is not rendered.
    #
    # A resumed session's continuation file repeats the records but the
    # subagent directory stays under the id that spawned them, so look beside
    # every file in the chain (the archived one, the requested one, and any
    # earlier/later half), deduplicating by agent id.
    agents: list[tuple[str, Path, Transcript]] = []
    chain_ids = [used, requested] + [r["session_id"] for r in related
                                      if r["relation"] in ("superset", "subset")]
    seen_agents: set[str] = set()
    for cid in chain_ids:
        if cid not in sessions:
            continue
        cpath = sessions[cid].path
        ag_dir = cpath.parent / cpath.stem / "subagents"
        if not ag_dir.is_dir():
            continue
        for af in sorted(ag_dir.glob("agent-*.jsonl")):
            aid = af.stem[len("agent-"):]
            if aid in seen_agents:
                continue
            seen_agents.add(aid)
            CON.detail(f"parsing subagent {af}")
            agents.append((aid, af, parse_transcript(af, max_tool_output)))
    # The cost meter is per process and a continuation file does not repeat
    # the earlier process's snapshots, so gather them from every file in the
    # chain. Keyed by startTime, duplicates collapse; the archived file wins.
    for cid in chain_ids:
        if cid in sessions and sessions[cid].path != path:
            for key, rec in cost_states_of(sessions[cid].path).items():
                t.cost_states.setdefault(key, rec)
    include_agents = subagents == "on"
    assign_tags(t)
    for _k, (_aid2, _af2, _at2) in enumerate(agents, 1):
        assign_tags(_at2, prefix=f"A{_k}.")
    for _aid, _af, at in agents:
        for model, agg in at.usage_by_model.items():
            for k, v in agg.items():
                t.usage_by_model[model][k] += v

    ts_dt = sorted(parse_ts(s) for s in t.timestamps)
    started, ended = (ts_dt[0], ts_dt[-1]) if ts_dt else (archived_at, archived_at)
    wall = ended - started

    if t.turn_duration_records:
        active = fmt_dur_ms(t.turn_durations_ms)
        active_note = f"summed from {t.turn_duration_records} turn_duration records"
    else:
        gap_cap = datetime.timedelta(minutes=20)
        acc = sum(((b - a) for a, b in zip(ts_dt, ts_dt[1:]) if (b - a) <= gap_cap),
                  datetime.timedelta())
        active = fmt_dur_ms(int(acc.total_seconds() * 1000))
        active_note = "estimated (no turn_duration records; gaps over 20m ignored)"

    # ---- pagination layout, decided before any HTML is rendered ------------
    # Units: one per main turn, then (when rendered) one subagent header and
    # one per subagent block. Knowing each unit's page up front lets links to
    # a subagent transcript carry the right page file with no post-editing.
    n_turn_units = len(t.turns)
    have_blocks = bool(agents) and include_agents
    total_units = n_turn_units + (1 + len(agents) if have_blocks else 0)
    per_page = max(0, paginate)
    n_pages = max(1, -(-total_units // per_page)) if per_page else 1

    def page_of(unit_idx: int) -> int:
        return unit_idx // per_page + 1 if per_page else 1

    def page_file(k: int) -> str:
        return out_path.name if k == 1 else f"{out_path.stem}_p{k}.html"

    agent_href = {}
    if have_blocks:
        for i, (aid, _af, _at) in enumerate(agents):
            k = page_of(n_turn_units + 1 + i)
            agent_href[aid] = ("" if k == 1 else page_file(k)) + f"#subagent-{aid}"

    units, toc = render_turns(t, agent_href=agent_href)
    rc = reported_cost(t, started)
    usage_html, usage_totals = usage_table(t, started.date(), rc)
    if agents:
        usage_html += (f'<p class="muted small">Totals include '
                       f'{len(agents)} subagent transcript(s).</p>')

    sub_toc: list[tuple[str, str, str]] = []
    if have_blocks:
        units.append((
            '<section class="turn report-turn" id="subagents">'
            '<div class="turn-label"><span class="who">Subagent transcripts</span></div>'
            '<div class="turn-body report-body"><p>Conversations run by background '
            'agents this session spawned. Each lives in its own file beside the '
            'session and is rendered here in full, with the same rules as the '
            'main transcript.</p></div></section>', "subagents"))
        for k, (aid, af, at) in enumerate(agents, 1):
            inner_units, _ = render_turns(at, anchor_prefix=f"sa-{aid}-")
            inner = "".join(h for h, _a in inner_units)
            n_rec = sum(at.record_types.values())
            units.append((f"""
<section class="turn subagent-block" id="subagent-{esc(aid)}" data-lane="subagent">
  <details>
    <summary><span class="chip harness-chip">subagent</span> <span class="rtag">A{k}</span> <code>agent-{esc(aid)}</code>
      <span class="evidence">{n_rec:,} records &middot; {len(at.turns):,} turns &middot; turns tagged A{k}.P/A{k}.R</span></summary>
    <div class="subagent-body">{inner}</div>
  </details>
</section>""", f"subagent-{aid}"))
            sub_toc.append((f"subagent-{aid}", f"A{k} · agent-{aid[:8]}", "system"))

    chain_html = ""
    if related:
        items = []
        for r in related:
            mark = " (archived here)" if r["session_id"] == used else ""
            items.append(
                f"<li><code>{esc(r['session_id'][:8])}</code> &mdash; {r['relation']}, "
                f"{r['shared']:,} shared records, {r['records']:,} total{mark}</li>")
        chain_html = (
            '<div class="callout"><strong>This conversation spans more than one transcript '
            'file.</strong> A resumed or bridged session is written to a new <code>.jsonl</code> '
            'that repeats the earlier records, so the most complete file is the one archived here.'
            f'<ul>{"".join(items)}</ul></div>')

    def info_row(k, v, title_attr=""):
        ta = f' title="{esc(title_attr)}"' if title_attr else ""
        return f"<dt>{esc(k)}</dt><dd{ta}>{v}</dd>"

    models_str = ", ".join(f"{esc(m)}" for m in sorted(t.models))
    session_info = "".join([
        info_row("Session ID", f"<code>{esc(used)}</code>"),
        info_row("Requested", f"<code>{esc(requested)}</code>") if used != requested else "",
        info_row("Started", esc(fmt_local(started)), fmt_utc(started)),
        info_row("Last record", esc(fmt_local(ended)), fmt_utc(ended)),
        info_row("Archived at", esc(fmt_local(archived_at)), fmt_utc(archived_at)),
        info_row("Wall clock", esc(fmt_dur_ms(int(wall.total_seconds() * 1000)))),
        info_row("Active time", esc(active), active_note),
        info_row("Models", models_str),
        info_row("Effort", ", ".join(f"{k} ×{v}" for k, v in t.effort.most_common())) if t.effort else "",
        info_row("Claude Code", f"v{esc(t.version or '?')}"),
        info_row("Working dir", f"<code>{esc(t.cwd or '')}</code>"),
        info_row("Human turns", f"{t.rendered_types.get('human turn', 0):,}"),
        info_row("Claude messages", f"{t.rendered_types.get('assistant text', 0):,}"),
        info_row("Thinking blocks",
                 f"{t.rendered_types.get('thinking', 0):,} with text, "
                 f"{t.empty_thinking:,} empty",
                 "Claude Code requests thinking with display=omitted, so the reasoning text is "
                 "never written to the transcript"),
        info_row("Tool calls", f"{t.rendered_types.get('tool call', 0):,}"),
        info_row("Subagents",
                 f"{len(agents)} transcript(s), "
                 f"{sum(sum(at.record_types.values()) for _, _, at in agents):,} records"
                 + ("" if include_agents else " (not rendered: --subagents off)"))
        if agents else "",
        info_row("Harness events",
                 f"{sum(v for k, v in t.rendered_types.items() if k.startswith(('harness', 'system'))):,}"),
        info_row("Output tokens", f"{usage_totals['output']:,}"),
        info_row("Cache reads", f"{usage_totals['cache_read']:,}"),
        info_row("List cost", f"${usage_totals['cost']:,.2f}"),
        info_row("Reported cost",
                 f"${rc['usd']:,.2f} reported by Claude Code ({rc['runs']} run(s)"
                 + (", partial: earlier runs not covered" if rc["partial"] else "") + ")")
        if rc else "",
        info_row("Compactions", f"{len(t.compactions):,}") if t.compactions else "",
        info_row("Skills used", esc(", ".join(sorted(t.skills)))) if t.skills else "",
    ])

    anchor_page = {"summary": 1, "usage": 1, "fidelity": 1}
    for i, (_h, a) in enumerate(units):
        if a:
            anchor_page[a] = page_of(i)

    def href_to(anchor: str, cur_page: int) -> str:
        p = anchor_page.get(anchor, 1)
        return f"#{anchor}" if p == cur_page else f"{page_file(p)}#{anchor}"

    def toc_for(cur_page: int) -> str:
        items = [
            f'<a href="{href_to("summary", cur_page)}" class="toc-item toc-key">Session summary</a>',
            f'<a href="{href_to("usage", cur_page)}" class="toc-item toc-key">Usage &amp; cost</a>',
            f'<a href="{href_to("fidelity", cur_page)}" class="toc-item toc-key">Fidelity report</a>']
        for anchor, label, cls in toc + sub_toc:
            items.append(f'<a href="{href_to(anchor, cur_page)}" '
                         f'class="toc-item toc-{cls}">{esc(label)}</a>')
        return "\n".join(items)

    def nav_for(cur_page: int) -> str:
        if n_pages == 1:
            return ""
        parts = [f"Page {cur_page} of {n_pages}"]
        if cur_page > 1:
            parts.append(f'<a href="{page_file(cur_page - 1)}">&larr; prev</a>')
        for k in range(1, n_pages + 1):
            parts.append(f"<strong>{k}</strong>" if k == cur_page
                         else f'<a href="{page_file(k)}">{k}</a>')
        if cur_page < n_pages:
            parts.append(f'<a href="{page_file(cur_page + 1)}">next &rarr;</a>')
        return '<nav class="page-nav">' + " &middot; ".join(parts) + "</nav>"

    meta = {
        "archiver_version": VERSION,
        "session_id": used,
        "requested_session_id": requested,
        "title": title,
        "started": started.isoformat(),
        "last_record": ended.isoformat(),
        "archived_at": archived_at.isoformat(),
        "source": str(path),
        "source_kind": source_kind or sessions[used].source,
        "records": sum(t.record_types.values()),
        "human_turns": t.rendered_types.get("human turn", 0),
        "assistant_messages": t.rendered_types.get("assistant text", 0),
        "thinking_blocks": t.rendered_types.get("thinking", 0),
        "tool_calls": t.rendered_types.get("tool call", 0),
        "output_tokens": usage_totals["output"],
        "cache_read_tokens": usage_totals["cache_read"],
        "list_cost_usd": round(usage_totals["cost"], 4),
        "reported_cost_usd": round(rc["usd"], 4) if rc else None,
        "reported_cost_runs": rc["runs"] if rc else 0,
        "reported_cost_partial": rc["partial"] if rc else None,
        "lines_added": rc["lines_added"] if rc else None,
        "lines_removed": rc["lines_removed"] if rc else None,
        "models": sorted(t.models),
        "chain": related,
        "subagents": [{"agent_id": aid,
                       "records": sum(at.record_types.values()),
                       "turns": len(at.turns),
                       "rendered": include_agents}
                      for aid, _, at in agents],
        "pages": [page_file(k) for k in range(1, n_pages + 1)],
    }

    subtitle = (f"{fmt_local(started)} – {fmt_local(ended)} · "
                f"{t.rendered_types.get('human turn', 0)} human turns · "
                f"{t.rendered_types.get('tool call', 0)} tool calls · "
                + (f"${rc['usd']:,.2f} reported by Claude Code"
                   if rc and not rc["partial"] else
                   f"${usage_totals['cost']:,.2f} at list price"))

    lead_html = (chain_html
                 + '<section class="turn summary-turn" id="summary">'
                   '<div class="turn-label"><span class="who">Session summary</span></div>'
                   f'<div class="turn-body summary-body">{summary_inner}</div></section>'
                 + '<section class="turn usage-turn" id="usage">'
                   '<div class="turn-label"><span class="who">Usage &amp; cost</span></div>'
                   f'<div class="turn-body usage-body">{usage_html}</div></section>'
                 + fidelity_section(t, path, archived_at, agents=agents,
                                    subagents_on=include_agents))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = []
    if "html" in formats:
        # CSS and JS ride in as .format *values*: format never scans values
        # for braces or fields, so neither their own braces nor any
        # placeholder-looking text inside the transcript body can trigger a
        # second substitution. "</" is escaped in the embedded JSON ("<\/" is
        # valid JSON) so a title containing "</script>" cannot terminate the
        # metadata block early.
        for k in range(1, n_pages + 1):
            chunk = (units[(k - 1) * per_page: k * per_page] if per_page
                     else units)
            page = _TEMPLATE.format(
                title=esc(title) + (f" — page {k}/{n_pages}" if n_pages > 1 else ""),
                session_info=session_info,
                toc_html=toc_for(k),
                page_nav=nav_for(k),
                lead_html=lead_html if k == 1 else "",
                body_html="\n".join(h for h, _a in chunk),
                meta_json=(json.dumps(meta, ensure_ascii=False)
                           if k == 1 else
                           json.dumps({"continuation_of": used, "page": k},
                                      ensure_ascii=False)
                           ).replace("</", "<\\/"),
                subtitle=esc(subtitle),
                css=_CSS,
                js=_JS,
            )
            q = out_path if k == 1 else out_path.with_name(page_file(k))
            q.write_text(page, encoding="utf-8")
            written.append((q, len(page)))

    ctx = {"title": title, "session_id": used, "subtitle": subtitle,
           "summary_text": html_fragment_to_text(summary_inner) if summary_inner else "",
           "cost_note": reported_cost_note(rc)}

    # Format and tool-output are independent: the script does not infer one from
    # the other. Tool arguments are pretty-printed wherever they appear, so this
    # is purely a question of length -- full I/O turns a 1,600-record session
    # into a several-hundred-page PDF.
    include_io = tool_output == "on"

    if "text" in formats:
        body = emit_text(t, ctx, tool_output=include_io, agents=agents,
                         subagents_on=include_agents)
        q = out_path.with_suffix(".txt")
        q.write_text(body, encoding="utf-8")
        written.append((q, len(body)))

    if "markdown" in formats:
        body = emit_markdown(t, ctx, tool_output=include_io, agents=agents,
                             subagents_on=include_agents)
        q = out_path.with_suffix(".md")
        q.write_text(body, encoding="utf-8")
        written.append((q, len(body)))

    if "latex" in formats or "pdf" in formats:
        src, tally = emit_latex(t, ctx, fragment=fragment,
                                tool_output=include_io, agents=agents,
                                subagents_on=include_agents)
        stem = out_path.stem + ("_fragment" if fragment else "")
        q = out_path.with_name(stem + ".tex")
        q.write_text(src, encoding="utf-8")
        written.append((q, len(src)))
        if tally["glyphs"] or tally["controls"]:
            CON.say(f"  note: LaTeX rendering dropped {tally['glyphs']:,} unsettable glyphs "
                    f"and {tally['controls']:,} control bytes (recorded in the document)")
        if "pdf" in formats:
            if fragment:
                sys.exit("--fragment cannot be compiled: it has no preamble. "
                         "Drop --fragment to build a PDF.")
            CON.detail(f"compiling {q.name} with xelatex (two passes)")
            pdf = compile_pdf(q)
            written.append((pdf, pdf.stat().st_size))
            if "latex" not in formats:
                q.unlink(missing_ok=True)
                written = [w for w in written if w[0] != q]

    for q, size in written:
        CON.say(f"wrote {q} ({size / 1e6:.2f} MB)")
    CON.say(f"  human={t.rendered_types.get('human turn', 0)} "
            f"assistant={t.rendered_types.get('assistant text', 0)} "
            f"thinking={t.rendered_types.get('thinking', 0)} "
            f"tools={t.rendered_types.get('tool call', 0)} "
            f"harness={sum(v for k, v in t.rendered_types.items() if k.startswith('harness'))} "
            f"events={sum(v for k, v in t.rendered_types.items() if k.startswith('system'))}")
    CON.say(f"  records={sum(t.record_types.values())} rendered={sum(t.rendered_types.values())} "
            f"counted-only={sum(t.counted_only.values())} unresolved-tools={t.unresolved_tools}")
    if agents:
        CON.say(f"  subagents={len(agents)} transcript(s), "
                f"{sum(sum(at.record_types.values()) for _, _, at in agents)} records"
                + ("" if include_agents else " (not rendered: --subagents off)"))
    CON.say(f"  output={usage_totals['output']:,} tok  cache-read={usage_totals['cache_read']:,} tok  "
            f"list-cost=${usage_totals['cost']:,.2f}"
            + (f"  reported=${rc['usd']:,.2f} ({rc['runs']} run(s)"
               f"{', partial' if rc['partial'] else ''})" if rc else ""))
    disp = t.disposition
    if disp["rendered"] + disp["folded"] + disp["counted"] != sum(t.record_types.values()):
        CON.note("warning: fidelity report does not reconcile -- a record class is "
                 "escaping the parser; the page says so")
    for k, v in t.counted_only.items():
        if k.startswith("unhandled record type"):
            CON.note(f"warning: {v} record(s) of an unhandled type were counted, not rendered: {k}")
    return meta


# ---------------------------------------------------------------------------
# Alternate output formats
#
# All of these render from the same parsed Transcript the HTML uses, so a turn
# cannot appear in one format and vanish from another. Each states what its own
# medium cannot carry -- the no-silent-drops contract applies per format, not
# just to the HTML.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Engine-neutral transliteration (--fragment)
#
# The standalone document is XeLaTeX and sets Unicode as itself. A fragment is
# different: it is \input into someone else's manuscript, and that manuscript
# picks the engine. pdflatex is 8-bit and stops the run on any character it has
# no declaration for -- across this machine's 37 conversations that is 209
# distinct characters, 14,962 occurrences, including the Greek that carries the
# physics. So a fragment transliterates.
#
# Two targets, because they have different rules:
#   prose    -- math mode is available, so Gamma becomes $\Gamma$
#   verbatim -- no macros, no math, no escapes at all: pure ASCII
# ---------------------------------------------------------------------------

_GREEK_NAMES = {
    0x391: "Alpha", 0x392: "Beta", 0x393: "Gamma", 0x394: "Delta",
    0x395: "Epsilon", 0x396: "Zeta", 0x397: "Eta", 0x398: "Theta",
    0x399: "Iota", 0x39A: "Kappa", 0x39B: "Lambda", 0x39C: "Mu",
    0x39D: "Nu", 0x39E: "Xi", 0x39F: "Omicron", 0x3A0: "Pi",
    0x3A1: "Rho", 0x3A3: "Sigma", 0x3A4: "Tau", 0x3A5: "Upsilon",
    0x3A6: "Phi", 0x3A7: "Chi", 0x3A8: "Psi", 0x3A9: "Omega",
    0x3B1: "alpha", 0x3B2: "beta", 0x3B3: "gamma", 0x3B4: "delta",
    0x3B5: "epsilon", 0x3B6: "zeta", 0x3B7: "eta", 0x3B8: "theta",
    0x3B9: "iota", 0x3BA: "kappa", 0x3BB: "lambda", 0x3BC: "mu",
    0x3BD: "nu", 0x3BE: "xi", 0x3BF: "omicron", 0x3C0: "pi",
    0x3C1: "rho", 0x3C3: "sigma", 0x3C4: "tau", 0x3C5: "upsilon",
    0x3C6: "phi", 0x3C7: "chi", 0x3C8: "psi", 0x3C9: "omega",
    0x3C2: "varsigma",
}

# ASCII-only, safe inside Verbatim.
_ASCII_MAP = {
    "\u2192": "->", "\u2190": "<-", "\u2194": "<->", "\u21d2": "=>",
    "\u21d0": "<=", "\u21d4": "<=>", "\u2191": "^", "\u2193": "v",
    "\u2248": "~=", "\u2260": "!=", "\u2264": "<=", "\u2265": ">=",
    "\u00b1": "+/-", "\u00d7": "x", "\u00f7": "/", "\u2212": "-",
    "\u221e": "inf", "\u2211": "sum", "\u220f": "prod", "\u222b": "int",
    "\u221a": "sqrt", "\u2202": "d", "\u2207": "grad", "\u2208": "in",
    "\u2209": "notin", "\u2282": "subset", "\u2286": "subseteq",
    "\u222a": "union", "\u2229": "intersect", "\u2205": "empty",
    "\u2261": "===", "\u221d": "prop", "\u22c5": ".", "\u00b7": ".",
    "\u2022": "*", "\u25e6": "o", "\u25aa": "-", "\u25cf": "*", "\u25cb": "o",
    "\u2713": "[ok]", "\u2714": "[ok]", "\u2705": "[ok]",
    "\u2717": "[x]", "\u2718": "[x]", "\u274c": "[x]", "\u2611": "[x]",
    "\u2612": "[x]", "\u26a0": "[!]", "\u2757": "[!]", "\u2139": "[i]",
    "\u2026": "...", "\u2013": "-", "\u2014": "--", "\u2018": "'",
    "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u00a0": " ",
    "\u23af": "-", "\u2500": "-", "\u2501": "=", "\u2502": "|", "\u2503": "|",
    "\u250c": "+", "\u2510": "+", "\u2514": "+", "\u2518": "+",
    "\u251c": "+", "\u2524": "+", "\u252c": "+", "\u2534": "+", "\u253c": "+",
    "\u2550": "=", "\u2551": "|", "\u2554": "+", "\u2557": "+",
    "\u255a": "+", "\u255d": "+", "\u2560": "+", "\u2563": "+",
    "\u2566": "+", "\u2569": "+", "\u256c": "+",
    "\u2588": "#", "\u2589": "#", "\u258c": "#", "\u2590": "#",
    "\u2580": "#", "\u2584": "#", "\u2591": ".", "\u2592": ":", "\u2593": "#",
    "\u00b0": "deg", "\u00b5": "u", "\u2032": "'", "\u2033": '"',
    "\ufffd": "?", "\u200b": "", "\ufeff": "",
}
_SUPER = {"\u2070": "0", "\u00b9": "1", "\u00b2": "2", "\u00b3": "3",
          "\u2074": "4", "\u2075": "5", "\u2076": "6", "\u2077": "7",
          "\u2078": "8", "\u2079": "9", "\u207a": "+", "\u207b": "-",
          "\u207f": "n", "\u2071": "i"}
_SUB = {"\u2080": "0", "\u2081": "1", "\u2082": "2", "\u2083": "3",
        "\u2084": "4", "\u2085": "5", "\u2086": "6", "\u2087": "7",
        "\u2088": "8", "\u2089": "9", "\u208a": "+", "\u208b": "-"}

# Prose versions can use real math.
_MATH_MAP = {
    "\u2192": r"$\rightarrow$", "\u2190": r"$\leftarrow$",
    "\u2194": r"$\leftrightarrow$", "\u21d2": r"$\Rightarrow$",
    "\u21d0": r"$\Leftarrow$", "\u21d4": r"$\Leftrightarrow$",
    "\u2191": r"$\uparrow$", "\u2193": r"$\downarrow$",
    "\u2248": r"$\approx$", "\u2260": r"$\neq$", "\u2264": r"$\leq$",
    "\u2265": r"$\geq$", "\u00b1": r"$\pm$", "\u00d7": r"$\times$",
    "\u00f7": r"$\div$", "\u2212": r"$-$", "\u221e": r"$\infty$",
    "\u2211": r"$\sum$", "\u220f": r"$\prod$", "\u222b": r"$\int$",
    "\u221a": r"$\sqrt{\ }$", "\u2202": r"$\partial$", "\u2207": r"$\nabla$",
    "\u2208": r"$\in$", "\u2209": r"$\notin$", "\u2282": r"$\subset$",
    "\u2286": r"$\subseteq$", "\u222a": r"$\cup$", "\u2229": r"$\cap$",
    "\u2205": r"$\emptyset$", "\u2261": r"$\equiv$", "\u221d": r"$\propto$",
    "\u22c5": r"$\cdot$", "\u00b7": r"$\cdot$", "\u2022": r"$\bullet$",
    "\u2026": r"\ldots{}", "\u2013": "--", "\u2014": "---",
    "\u00b0": r"$^\circ$", "\u00b5": r"$\mu$", "\u2032": r"$'$",
}


def _greek(ch, verbatim):
    name = _GREEK_NAMES.get(ord(ch))
    if not name:
        return None
    return name if verbatim else "$\\" + name + "$"


def transliterate(s: str, tally, verbatim: bool) -> str:
    """Reduce text to what any TeX engine can set.

    verbatim=True yields pure ASCII (no macros survive a Verbatim body);
    verbatim=False may use math mode, which reads far better in prose.
    """
    # Collapse runs first: 10⁻⁶ should become 10$^{-6}$, not 10$^{-}$$^{6}$.
    def _run(m, table, mark):
        tally["transliterated"] += len(m.group(0))
        body = "".join(table[c] for c in m.group(0))
        return mark + body if verbatim else "$" + mark + "{" + body + "}$"

    s = re.sub("[" + "".join(_SUPER) + "]+",
               lambda m: _run(m, _SUPER, "^"), s)
    s = re.sub("[" + "".join(_SUB) + "]+",
               lambda m: _run(m, _SUB, "_"), s)

    out = []
    for ch in s:
        cp = ord(ch)
        if cp < 0x80:
            out.append(ch)
            continue
        g = _greek(ch, verbatim)
        if g is not None:
            tally["transliterated"] += 1
            out.append(g)
            continue
        table = _ASCII_MAP if verbatim else {**_ASCII_MAP, **_MATH_MAP}
        if ch in table:
            tally["transliterated"] += 1
            out.append(table[ch])
            continue
        if ch in _SUPER:
            tally["transliterated"] += 1
            out.append("^" + _SUPER[ch] if verbatim else "$^{" + _SUPER[ch] + "}$")
            continue
        if ch in _SUB:
            tally["transliterated"] += 1
            out.append("_" + _SUB[ch] if verbatim else "$_{" + _SUB[ch] + "}$")
            continue
        # Accented Latin: keep the base letter rather than lose the word.
        decomposed = unicodedata.normalize("NFD", ch)
        stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
        if stripped and all(ord(c) < 0x80 for c in stripped):
            if stripped != ch:
                tally["transliterated"] += 1
            out.append(stripped)
            continue
        tally["glyphs"] += 1
    return "".join(out)


_ANSI_RE = re.compile("\x1b\\[[0-9;?]*[a-zA-Z]")
_TEX_SPECIALS = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$",
                 "&": r"\&", "#": r"\#", "^": r"\textasciicircum{}",
                 "_": r"\_", "~": r"\textasciitilde{}", "%": r"\%"}


def strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def tex_escape(s: str) -> str:
    return "".join(_TEX_SPECIALS.get(ch, ch) for ch in s)


_TEX_CHAR_MAP = {"\u2713": "[ok]", "\u2714": "[ok]", "\u2717": "[x]",
                 "\u2718": "[x]", "\u2611": "[x]", "\u2612": "[x]"}


def tex_drop_unprintable(s: str, tally) -> str:
    """Remove codepoints no TeX font on this machine can set.

    Missing glyphs are only warnings to XeTeX, but emoji render as blanks and
    astral-plane characters can upset the shaper. They are counted so the
    document can say how many it dropped instead of dropping them quietly.
    """
    out = []
    for ch in s:
        if ch in _TEX_CHAR_MAP:
            out.append(_TEX_CHAR_MAP[ch])
            continue
        cp = ord(ch)
        # C0/C1 control bytes. Real tool output carries them: a Windows command
        # emitting UTF-16LE, captured byte-wise, interleaves a NUL between every
        # letter (1,701 of them in one session), and backspaces show up in
        # progress output. A browser ignores them in a text node; TeX stops with
        # "Text line contains an invalid character".
        if (cp < 0x20 and ch not in "\n\t") or 0x7F <= cp <= 0x9F:
            tally["controls"] += 1
            continue
        if cp >= 0x1F000 or 0xFE00 <= cp <= 0xFE0F or cp == 0x200D:
            tally["glyphs"] += 1
            continue
        out.append(ch)
    return "".join(out)


def tex_inline(s: str, tally, neutral: bool = False) -> str:
    """Markdown inline spans -> LaTeX, applied after escaping."""
    s = tex_drop_unprintable(strip_ansi(s), tally)
    # Escape BEFORE transliterating. tex_escape only rewrites ASCII specials and
    # transliterate only rewrites characters above U+007F, so the two never
    # touch the same character and the order is safe. Doing it the other way
    # round meant the emitted math had to be shielded from the escaper by a
    # regex -- and that regex could not tell a macro this code generated from a
    # literal \mathbf{r} quoted in the transcript, so real prose about LaTeX
    # escaped unescaped and stopped the compile.
    s = tex_escape(s)
    if neutral:
        s = transliterate(s, tally, verbatim=False)
    s = s.replace("\\textbackslash{}", "\\textbackslash{}\\allowbreak{}")
    s = re.sub(r"(?<=[/_])(?=[^\s/_]{6})", lambda m: "\\allowbreak{}", s)
    s = re.sub(r"`([^`]+)`", r"\\texttt{\1}", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\\textbf{\1}", s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"\\emph{\1}", s)
    return s


_TEX_HARD_WRAP = 500

# A breakable tcolorbox first typesets its whole content into one box, so a
# single enormous verbatim turn exhausts TeX's main memory: on the real
# archive a 9,614-line paste failed with "TeX capacity exceeded" while 4,000
# lines in one box compiled and the same paste as consecutive 1,500-line
# boxes compiled. Turns beyond this many (wrapped) lines are split into
# consecutive boxes titled "(part k/n)", and the document says so.
_TEX_BOX_MAX_LINES = 1500


def _verbatim_chunks(text: str) -> list[str]:
    """Split verbatim text into pieces of at most _TEX_BOX_MAX_LINES typeset
    lines, counting the hard wrap a long line will get. One piece for the
    common case."""
    lines = text.split("\n")
    def cost(ln):
        return max(1, -(-len(ln) // _TEX_HARD_WRAP))
    if sum(cost(ln) for ln in lines) <= _TEX_BOX_MAX_LINES:
        return [text]
    chunks, cur, n = [], [], 0
    for ln in lines:
        c = cost(ln)
        if cur and n + c > _TEX_BOX_MAX_LINES:
            chunks.append("\n".join(cur))
            cur, n = [], 0
        cur.append(ln)
        n += c
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def tex_verbatim(body: str, tally, neutral: bool = False) -> str:
    body = tex_drop_unprintable(strip_ansi(body), tally)
    if neutral:
        body = transliterate(body, tally, verbatim=True)
    body = body.replace("\\end{Verbatim}", "\\end{Verb atim}")
    # breakanywhere gives TeX a break opportunity after every character, so a
    # single enormous line becomes one paragraph with tens of thousands of them
    # and the line breaker crawls: one session with a 65,110-character line took
    # 928s to typeset 57 pages. Pre-splitting keeps each paragraph bounded. The
    # visual result is the same wrap fvextra would have chosen.
    if any(len(ln) > _TEX_HARD_WRAP for ln in body.split("\n")):
        wrapped = []
        for ln in body.split("\n"):
            if len(ln) <= _TEX_HARD_WRAP:
                wrapped.append(ln)
            else:
                tally["hardwrapped"] += 1
                wrapped += [ln[i:i + _TEX_HARD_WRAP]
                            for i in range(0, len(ln), _TEX_HARD_WRAP)]
        body = "\n".join(wrapped)
    if not body.strip():
        body = "(empty)"
    opts = "breaklines=true,breakanywhere=true,fontsize=\\small,xleftmargin=6pt"
    return "\\begin{Verbatim}[" + opts + "]\n" + body + "\n\\end{Verbatim}\n"


def md_to_tex(text: str, tally, neutral: bool = False) -> str:
    def inl(x):
        return tex_inline(x, tally, neutral)

    def verb(x):
        return tex_verbatim(x, tally, neutral)

    out = []
    for tok in md_tokens(text):
        if tok[0] == "para":
            out.append(inl(tok[1]) + "\n\n")
        elif tok[0] == "code":
            out.append(verb(tok[2]))
        elif tok[0] == "heading":
            cmd = ["\\subsection*", "\\subsubsection*", "\\paragraph"][min(tok[1] - 1, 2)]
            out.append(cmd + "{" + inl(tok[2]) + "}\n")
        elif tok[0] == "hr":
            out.append("\\medskip\\hrule\\medskip\n")
        elif tok[0] == "table":
            header, rows = tok[1], tok[2]
            ncol = max(1, len(header))
            out.append("\\begin{tabular}{" + "l" * ncol + "}\n\\toprule\n")
            out.append(" & ".join(inl(c) for c in header) + " \\\\\n\\midrule\n")
            for r in rows:
                cells = (list(r) + [""] * ncol)[:ncol]
                out.append(" & ".join(inl(c) for c in cells) + " \\\\\n")
            out.append("\\bottomrule\n\\end{tabular}\n\n")
        elif tok[0] == "list":
            # Group consecutive items by marker type so a list that switches
            # from bullets to numbers gets enumerate for the numbered run
            # instead of one flattened itemize. (Nesting stays flat here; the
            # HTML keeps the hierarchy.)
            items, j = tok[1], 0
            while j < len(items):
                ordered = items[j][1]
                env = "enumerate" if ordered else "itemize"
                out.append("\\begin{" + env + "}[leftmargin=*,itemsep=1pt]\n")
                while j < len(items) and items[j][1] == ordered:
                    out.append("  \\item " + inl(items[j][2]) + "\n")
                    j += 1
                out.append("\\end{" + env + "}\n")
        elif tok[0] == "quote":
            out.append("\\begin{quote}\n" + inl(tok[1]) + "\n\\end{quote}\n")
    return "".join(out)


def html_fragment_to_text(frag: str) -> str:
    """Flatten a hand-written summary fragment to readable plain text."""
    s = re.sub(r"(?is)<(h[1-6])[^>]*>(.*?)</\1>",
               lambda m: "\n\n" + m.group(2).upper() + "\n", frag)
    s = re.sub(r"(?is)<li[^>]*>", "\n  - ", s)
    s = re.sub(r"(?is)</(p|div|ul|ol|li|section)>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", "", s)
    for a, b in (("&mdash;", "--"), ("&ndash;", "-"), ("&nbsp;", " "),
                 ("&ldquo;", '"'), ("&rdquo;", '"'), ("&rsquo;", "'"),
                 ("&lsquo;", "'"), ("&middot;", "-"), ("&hellip;", "..."),
                 ("&times;", "x"), ("&asymp;", "~"), ("&le;", "<="),
                 ("&ge;", ">="), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">")):
        s = s.replace(a, b)
    s = re.sub(r"&[a-zA-Z]+;", "", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def fidelity_lines(t) -> list:
    """The four reconciliation numbers, identical in every format."""
    d = t.disposition
    return [("records that produced one or more turns below", d["rendered"]),
            ("records folded into an earlier turn (tool results)", d["folded"]),
            ("records counted only (no transcript content)", d["counted"]),
            ("total records in the source", sum(t.record_types.values()))]


def soft_wrap(text: str, width: int = 100) -> str:
    """Wrap over-long prose lines; leave columnar or already-short lines alone."""
    out = []
    for line in text.split("\n"):
        if len(line) <= width or "  " in line.strip() or "\t" in line:
            out.append(line)
        else:
            out.extend(textwrap.wrap(line, width=width) or [""])
    return "\n".join(out)


def wrap_prose(text: str, width: int = 100, indent: str = "") -> str:
    """Wrap authored prose. Never applied to human turns or tool I/O."""
    out = []
    for block in text.split("\n\n"):
        para = " ".join(block.split())
        out.append(textwrap.fill(para, width=width, initial_indent=indent,
                                 subsequent_indent=indent) if para else "")
    return "\n\n".join(out)


_NOTE_WITH_IO = ("Every turn in the HTML archive is present here, with tool input and "
                 "output in full. Images embedded in tool results cannot travel in this "
                 "format and are marked as omitted; ANSI colour codes are stripped. Human "
                 "turns and tool output are reproduced verbatim and are never re-wrapped.")

_NOTE_NO_IO = ("Every turn in the HTML archive is present here, but tool calls are reduced "
               "to a single labelled line: their input and output are omitted, because a "
               "page-based format renders them as unreadable walls of escaped JSON. The "
               "HTML archive holds all of it. Human turns and Claude's prose are complete "
               "and reproduced verbatim.")


def _format_note(tool_output: bool, omitted: int) -> str:
    if tool_output:
        return _NOTE_WITH_IO
    return _NOTE_NO_IO + (f" {omitted:,} tool calls are shown by name only."
                          if omitted else "")


def _turn_rule(label: str, ts: str, width: int, right: bool) -> list:
    """A boxed turn header, right-shifted for human turns.

    The header moves; the body never does. Human turns and tool output are
    reproduced byte-for-byte, so indenting their content would break the one
    guarantee this format exists to give -- a chat look is not worth that.
    """
    tag = f"[ {label} - {ts} ]" if ts else f"[ {label} ]"
    fill = "=" if right else "-"
    if right:
        pad = max(0, width - len(tag))
        return [" " * pad + tag, " " * max(0, pad - 2) + fill * (len(tag) + 2)]
    return [tag, fill * min(width, max(len(tag), 60))]


def _text_turns(turns, L, W, tool_output):
    for turn in turns:
        ts = (turn.get("ts") or "")[:19].replace("T", " ")
        kind = turn["kind"]
        if kind == "human":
            label = "HUMAN" + (f" - {turn['tag']}" if turn.get("tag") else "")
            L += [""] + _turn_rule(label, ts, W, right=True) + ["", turn["text"].rstrip(), ""]
        elif kind == "assistant":
            label = ("CLAUDE" + (f" - {turn['tag']}" if turn.get("tag") else "")
                     + " " + str(turn.get("model", "")))
            L += [""] + _turn_rule(label, ts, W, right=False)
            L += ["", wrap_prose(turn.get("text", ""), W), ""]
        elif kind == "thinking":
            L += [""] + _turn_rule("THINKING", ts, W, right=False)
            L += ["", wrap_prose(turn.get("text", "") or "(no text: display=omitted)", W), ""]
        elif kind == "user_image":
            L += [""] + _turn_rule("HUMAN - PASTED IMAGE", ts, W, right=True)
            L += ["", "  (image omitted in this format; the HTML archive holds it)", ""]
        elif kind == "tool":
            err = "  [ERROR]" if turn.get("is_error") else ""
            head = shorten("TOOL " + str(turn.get("chip", "")) + " - "
                           + str(turn.get("label", "")) + err, 84)
            if not tool_output:
                L += ["", "  . " + head + "   " + ts]
                continue
            L += [""] + _turn_rule(head, ts, W, right=False) + ["", "  input:"]
            L += ["    " + ln
                  for ln in pretty_tool_input(turn.get("input") or "").splitlines()]
            if turn.get("output_text"):
                L += ["", "  output:"]
                L += ["    " + ln for ln in turn["output_text"].splitlines()]
            elif not turn.get("resolved"):
                L += ["", "  output: (no result in the source)"]
            for _ in turn.get("output_images") or []:
                L.append("    [image omitted]")
            L.append("")
        else:
            L += [""] + _turn_rule(str(turn.get("badge", kind)).upper(), ts, W, right=False)
            L += ["", soft_wrap((turn.get("text") or "").rstrip(), W), ""]


def emit_text(t, ctx: dict, tool_output: bool = True, agents: list = (),
              subagents_on: bool = True) -> str:
    W = 100
    bar = "=" * W
    L = [bar, "  " + ctx["title"], "  session " + ctx["session_id"],
         "  " + ctx["subtitle"], bar, ""]
    if ctx["summary_text"]:
        L += ["SESSION SUMMARY", "-" * 15, "", wrap_prose(ctx["summary_text"], W), ""]
    L += ["FIDELITY REPORT", "-" * 15, ""]
    for label, n in fidelity_lines(t):
        L.append("  " + label.ljust(52) + format(n, ",").rjust(9))
    for aid, _af, at in agents:
        L.append("  " + f"subagent transcript agent-{aid}"
                 f"{'' if subagents_on else ' (not rendered)'}".ljust(52)
                 + format(sum(at.record_types.values()), ",").rjust(9))
    n_tools = sum(1 for x in t.turns if x["kind"] == "tool")
    if ctx.get("cost_note"):
        L += ["", wrap_prose(ctx["cost_note"], W)]
    L += ["", wrap_prose(_format_note(tool_output, n_tools), W), ""]
    _text_turns(t.turns, L, W, tool_output)
    if agents and subagents_on:
        for k, (aid, _af, at) in enumerate(agents, 1):
            L += ["", bar,
                  f"  SUBAGENT TRANSCRIPT A{k}: agent-{aid}  "
                  f"({sum(at.record_types.values()):,} records; "
                  f"turns tagged A{k}.P / A{k}.R)", bar]
            _text_turns(at.turns, L, W, tool_output)
    return "\n".join(L) + "\n"


def _md_fence(text: str, lang: str = "") -> str:
    """Fence verbatim content with more backticks than any run inside it."""
    longest = max((len(r) for r in re.findall(r"`+", text)), default=0)
    f = "`" * max(3, longest + 1)
    return f"{f}{lang}\n{text}\n{f}"


def emit_markdown(t, ctx: dict, tool_output: bool = True, agents: list = (),
                  subagents_on: bool = True) -> str:
    """Markdown for note vaults. Claude's prose IS markdown and passes through
    live; human turns and tool I/O are fenced so nothing in them can be
    reinterpreted -- the same verbatim guarantee the text format gives."""
    L = [f"# {ctx['title']}", "",
         f"- Session: `{ctx['session_id']}`",
         f"- {ctx['subtitle']}", ""]
    if ctx["summary_text"]:
        L += ["## Session summary", "", ctx["summary_text"], ""]
    L += ["## Fidelity report", ""]
    for label, n in fidelity_lines(t):
        L.append(f"- {label}: {n:,}")
    for aid, _af, at in agents:
        L.append(f"- subagent transcript agent-{aid}"
                 f"{'' if subagents_on else ' (not rendered)'}: "
                 f"{sum(at.record_types.values()):,}")
    n_tools = sum(1 for x in t.turns if x["kind"] == "tool")
    if ctx.get("cost_note"):
        L += ["", ctx["cost_note"]]
    L += ["", _format_note(tool_output, n_tools),
          "Human turns and tool I/O are fenced verbatim below; Claude's own "
          "prose is markdown and is left live, so its headings appear in this "
          "document's outline.", ""]

    def turns_md(turns):
        for turn in turns:
            ts = (turn.get("ts") or "")[:19].replace("T", " ")
            kind = turn["kind"]
            if kind == "human":
                tg = f" - {turn['tag']}" if turn.get("tag") else ""
                L.extend([f"## Human{tg} — {ts}", "",
                          _md_fence(turn["text"].rstrip()), ""])
            elif kind == "assistant":
                tg = f" - {turn['tag']}" if turn.get("tag") else ""
                L.extend([f"## Claude{tg} — {ts}", "", turn.get("text", ""), ""])
            elif kind == "thinking":
                L.extend([f"### Thinking — {ts}", "",
                          turn.get("text", "") or "*(no text: display=omitted)*", ""])
            elif kind == "user_image":
                L.extend([f"## Human — pasted image — {ts}", "",
                          "*(image omitted in this format; the HTML archive "
                          "holds it)*", ""])
            elif kind == "tool":
                err = " **[ERROR]**" if turn.get("is_error") else ""
                head = shorten(str(turn.get("chip", "")) + " — "
                               + str(turn.get("label", "")), 90)
                L.append(f"**Tool · {head}**{err} · {ts}")
                if tool_output:
                    L.extend(["", _md_fence(pretty_tool_input(turn.get("input") or ""))])
                    if turn.get("output_text"):
                        L.extend(["", _md_fence(turn["output_text"])])
                    elif not turn.get("resolved"):
                        L.extend(["", "*(no result in the source)*"])
                    for _ in turn.get("output_images") or []:
                        L.extend(["", "*(image omitted in this format)*"])
                L.append("")
            else:
                badge = str(turn.get("badge", kind))
                L.append(f"> **{badge}** · {ts}")
                if turn.get("text"):
                    L.extend(["", _md_fence(turn["text"].rstrip())])
                L.append("")

    turns_md(t.turns)
    if agents and subagents_on:
        for k, (aid, _af, at) in enumerate(agents, 1):
            L.extend(["", "---", "",
                      f"# Subagent transcript A{k}: agent-{aid}",
                      f"*({sum(at.record_types.values()):,} records; a background "
                      "agent's own conversation)*", ""])
            turns_md(at.turns)
    return "\n".join(L) + "\n"


_TEX_PREAMBLE = r"""\documentclass[10pt,a4paper]{article}
\usepackage{fontspec}
\usepackage{fvextra}
\usepackage[margin=20mm]{geometry}
\usepackage{booktabs}
\usepackage{enumitem}
\usepackage{xcolor}
\usepackage[colorlinks=true,linkcolor=black,urlcolor=blue!60!black]{hyperref}
\IfFontExistsTF{DejaVuSerif.ttf}{%
  \setmainfont{DejaVuSerif.ttf}[BoldFont=DejaVuSerif-Bold.ttf,
    ItalicFont=DejaVuSerif-Italic.ttf,Scale=0.92]%
  \setsansfont{DejaVuSans.ttf}[BoldFont=DejaVuSans-Bold.ttf]%
  \setmonofont{DejaVuSansMono.ttf}[BoldFont=DejaVuSansMono-Bold.ttf,
    ItalicFont=DejaVuSansMono-Oblique.ttf,Scale=0.85]%
}{}
\usepackage[most]{tcolorbox}
\definecolor{paper}{HTML}{FAF7F0}
\pagecolor{paper}
\definecolor{humanc}{HTML}{2F6F4F}\definecolor{humanbg}{HTML}{E9F3ED}
\definecolor{claudec}{HTML}{44578C}\definecolor{claudebg}{HTML}{ECEFF8}
\definecolor{toolc}{HTML}{5C5750}\definecolor{toolbg}{HTML}{F1EFE9}
\definecolor{sysc}{HTML}{96762C}\definecolor{sysbg}{HTML}{F7EFDD}
\definecolor{thinkc}{HTML}{6B5B95}\definecolor{thinkbg}{HTML}{F0ECF6}
\newtcolorbox{humanturn}[1]{breakable,enhanced,colback=humanbg,colframe=humanc,
  boxrule=0.9pt,arc=3mm,left skip=0.16\linewidth,
  fonttitle=\bfseries\footnotesize,colbacktitle=humanc,coltitle=white,
  title={#1}}
\newtcolorbox{claudeturn}[1]{breakable,enhanced,colback=claudebg,colframe=claudec,
  boxrule=0.9pt,arc=3mm,right skip=0.10\linewidth,
  fonttitle=\bfseries\footnotesize,colbacktitle=claudec,coltitle=white,
  title={#1}}
\newtcolorbox{thinkturn}[1]{breakable,enhanced,colback=thinkbg,colframe=thinkc,
  boxrule=0.6pt,arc=2mm,right skip=0.10\linewidth,
  fonttitle=\bfseries\footnotesize,colbacktitle=thinkc,coltitle=white,
  title={#1}}
\newtcolorbox{toolturn}[1]{breakable,enhanced,colback=toolbg,colframe=toolc,
  boxrule=0.5pt,arc=1mm,fonttitle=\bfseries\scriptsize,colbacktitle=toolc,
  coltitle=white,title={#1}}
\newtcolorbox{systurn}[1]{breakable,enhanced,colback=sysbg,colframe=sysc,
  boxrule=0.5pt,arc=1mm,fonttitle=\bfseries\scriptsize,colbacktitle=sysc,
  coltitle=white,title={#1}}
\setlength{\parindent}{0pt}
\setlength{\parskip}{4pt}
\sloppy
\setlength{\emergencystretch}{4em}
"""


_FRAGMENT_HEAD = r"""% Transcript body only -- \input this into your own document.
%
% Engine-neutral: every character has been reduced to something pdflatex can
% set, so this compiles under pdflatex, xelatex or lualatex alike.
%
% It needs these packages in your preamble:
%     \usepackage{fvextra}   \usepackage{xcolor}   \usepackage{enumitem}
%     \usepackage{booktabs}  \usepackage[most]{tcolorbox}
%
% No \pagecolor is set here -- a fragment must not repaint its host's pages.
% The turn environments are defined only if you have not defined your own,
% so you can restyle every turn from your preamble without editing this file.
\providecolor{humanc}{HTML}{2F6F4F}\providecolor{humanbg}{HTML}{E9F3ED}
\providecolor{claudec}{HTML}{44578C}\providecolor{claudebg}{HTML}{ECEFF8}
\providecolor{toolc}{HTML}{5C5750}\providecolor{toolbg}{HTML}{F1EFE9}
\providecolor{sysc}{HTML}{96762C}\providecolor{sysbg}{HTML}{F7EFDD}
\providecolor{thinkc}{HTML}{6B5B95}\providecolor{thinkbg}{HTML}{F0ECF6}
\makeatletter
\@ifundefined{humanturn}{%
\newtcolorbox{humanturn}[1]{breakable,enhanced,colback=humanbg,colframe=humanc,
  boxrule=0.9pt,arc=3mm,left skip=0.16\linewidth,
  fonttitle=\bfseries\footnotesize,colbacktitle=humanc,coltitle=white,
  title={#1}}
\newtcolorbox{claudeturn}[1]{breakable,enhanced,colback=claudebg,colframe=claudec,
  boxrule=0.9pt,arc=3mm,right skip=0.10\linewidth,
  fonttitle=\bfseries\footnotesize,colbacktitle=claudec,coltitle=white,
  title={#1}}
\newtcolorbox{thinkturn}[1]{breakable,enhanced,colback=thinkbg,colframe=thinkc,
  boxrule=0.6pt,arc=2mm,right skip=0.10\linewidth,
  fonttitle=\bfseries\footnotesize,colbacktitle=thinkc,coltitle=white,
  title={#1}}
\newtcolorbox{toolturn}[1]{breakable,enhanced,colback=toolbg,colframe=toolc,
  boxrule=0.5pt,arc=1mm,fonttitle=\bfseries\scriptsize,colbacktitle=toolc,
  coltitle=white,title={#1}}
\newtcolorbox{systurn}[1]{breakable,enhanced,colback=sysbg,colframe=sysc,
  boxrule=0.5pt,arc=1mm,fonttitle=\bfseries\scriptsize,colbacktitle=sysc,
  coltitle=white,title={#1}}
}{}
\makeatother

"""


def emit_latex(t, ctx: dict, fragment: bool = False, tool_output: bool = False,
               agents: list = (), subagents_on: bool = True):
    # A fragment goes into someone else's document, so it must survive whatever
    # engine that document uses -- pdflatex included. The standalone stays
    # XeLaTeX and keeps Unicode as itself.
    neutral = fragment
    tally = Counter()

    def inl(x):
        return tex_inline(x, tally, neutral)

    def verb(x):
        return tex_verbatim(x, tally, neutral)

    def md(x):
        return md_to_tex(x, tally, neutral)

    def esc(x):
        """Escape a bare string -- a turn label, badge or id.

        These bypassed transliteration when they went straight to tex_escape,
        which let a tool label carrying a Greek capital or a subscript leak an
        un-settable character into an otherwise ASCII fragment.
        """
        x = tex_drop_unprintable(strip_ansi(str(x)), tally)
        if neutral:
            x = transliterate(x, tally, verbatim=True)
        return tex_escape(x)

    B = []
    if fragment:
        B.append(_FRAGMENT_HEAD)
    if not fragment:
        B.append(_TEX_PREAMBLE)
        B.append("\\title{" + inl(ctx["title"]) + "}\n\\date{}\n")
        B.append("\\begin{document}\n\\maketitle\n")
        B.append("\\begin{center}\\texttt{" + esc(ctx["session_id"]) + "}\\\\\n")
        B.append(inl(ctx["subtitle"]) + "\\end{center}\n")
        B.append("\\tableofcontents\n\\newpage\n")
    if ctx["summary_text"]:
        B.append("\\section*{Session summary}\n\\addcontentsline{toc}{section}{Session summary}\n")
        B.append(md(ctx["summary_text"]))
    B.append("\\section*{Fidelity report}\n\\addcontentsline{toc}{section}{Fidelity report}\n")
    B.append("\\begin{tabular}{lr}\n\\toprule\n")
    for label, n in fidelity_lines(t):
        B.append(esc(label) + " & " + format(n, ",") + " \\\\\n")
    B.append("\\bottomrule\n\\end{tabular}\n\n")
    n_tools = sum(1 for x in t.turns if x["kind"] == "tool")
    if ctx.get("cost_note"):
        B.append(inl(ctx["cost_note"]) + "\n\n")
    B.append(inl(_format_note(tool_output, n_tools)) + "\n\n")
    # The drop-note's numbers are only known once the whole body is rendered,
    # so reserve a slot and assign it afterwards. Filling it by string
    # replacement over the finished source once clobbered a transcript that
    # itself contained the placeholder text.
    B.append("")
    dropnote_slot = len(B) - 1
    B.append("\\section*{Transcript}\n\\addcontentsline{toc}{section}{Transcript}\n")
    def box(env, title, inner):
        return ("\\begin{" + env + "}{" + title + "}\n" + inner
                + "\\end{" + env + "}\n")

    def stamp(ts):
        return " \\hfill {\\normalfont\\scriptsize\\ttfamily " + esc(ts) + "}"

    def verbatim_boxes(env, label, ts, text, lead=""):
        """One box, or -- for a turn too large for one breakable box --
        consecutive boxes '(part k/n)'. `lead` (a tool call's input) goes
        into the first box only."""
        chunks = _verbatim_chunks(text)
        if len(chunks) == 1:
            B.append(box(env, label + stamp(ts), lead + verb(text)))
            return
        tally["split_boxes"] += 1
        for k, chunk in enumerate(chunks, 1):
            B.append(box(env, label + f" (part {k}/{len(chunks)})" + stamp(ts),
                         (lead if k == 1 else "") + verb(chunk)))

    def emit_turns(turns):
        for turn in turns:
            ts = (turn.get("ts") or "")[:19].replace("T", " ")
            kind = turn["kind"]
            if kind == "human":
                tg = (" - " + esc(turn["tag"])) if turn.get("tag") else ""
                verbatim_boxes("humanturn", "HUMAN" + tg, ts, turn["text"].rstrip())
            elif kind == "assistant":
                tg = (" - " + esc(turn["tag"])) if turn.get("tag") else ""
                B.append(box("claudeturn", "CLAUDE" + tg + " \\hfill {\\normalfont\\scriptsize\\ttfamily " + esc(ts) + "}",
                             md(turn.get("text", ""))))
            elif kind == "thinking":
                B.append(box("thinkturn", "THINKING" + " \\hfill {\\normalfont\\scriptsize\\ttfamily " + esc(ts) + "}",
                             md(turn.get("text", "") or "(no text: display=omitted)")))
            elif kind == "tool":
                err = " [ERROR]" if turn.get("is_error") else ""
                head = esc(shorten(str(turn.get("chip", "")) + " - "
                                   + str(turn.get("label", "")) + err))
                title = "TOOL: " + head + " \\hfill {\\normalfont\\scriptsize\\ttfamily " + esc(ts) + "}"
                if not tool_output:
                    # A bare title box: the call is on the record, its payload is not.
                    B.append("\\begin{toolturn}{" + title + "}\\end{toolturn}\n")
                    continue
                lead = verb(pretty_tool_input(turn.get("input") or ""))
                tail = ""
                if not turn.get("output_text") and not turn.get("resolved"):
                    tail += inl("(no result in the source)") + "\n\n"
                for _ in turn.get("output_images") or []:
                    tail += inl("[image omitted]") + "\n\n"
                if turn.get("output_text"):
                    verbatim_boxes("toolturn", "TOOL: " + head, ts, turn["output_text"], lead=lead)
                    if tail:
                        B.append(box("toolturn", "TOOL: " + head + " (images)" + stamp(ts), tail))
                else:
                    B.append(box("toolturn", title, lead + tail))
            elif kind == "user_image":
                B.append(box("humanturn",
                             "HUMAN - PASTED IMAGE \\hfill {\\normalfont\\scriptsize\\ttfamily " + esc(ts) + "}",
                             inl("(image omitted in this format; the HTML "
                                 "archive holds it)") + "\n\n"))
            else:
                badge = esc(shorten(str(turn.get("badge", kind))))
                verbatim_boxes("systurn", badge, ts, (turn.get("text") or "").rstrip())

    emit_turns(t.turns)
    if agents and subagents_on:
        for k, (aid, _af, at) in enumerate(agents, 1):
            B.append("\\section*{Subagent transcript A" + str(k) + ": agent-"
                     + esc(aid) + "}\n"
                     "\\addcontentsline{toc}{section}{Subagent A" + str(k)
                     + ": agent-" + esc(aid[:8]) + "}\n")
            B.append(inl(f"({sum(at.record_types.values()):,} records; a background "
                         "agent's own conversation, archived from its transcript "
                         "file beside the session)") + "\n\n")
            emit_turns(at.turns)
    elif agents:
        B.append("\\section*{Subagent transcripts (not rendered)}\n")
        B.append(inl(f"{len(agents)} subagent transcript file(s) exist for this "
                     "session but were not rendered (--subagents off): "
                     + ", ".join(f"agent-{a}" for a, _, _ in agents)
                     + ". Their token usage is included in the usage table.")
                 + "\n\n")
    if not fragment:
        B.append("\\end{document}\n")
    removed = []
    if tally["glyphs"]:
        removed.append(format(tally["glyphs"], ",") + " characters (emoji and other glyphs "
                       "no installed TeX font can set)")
    if tally["controls"]:
        removed.append(format(tally["controls"], ",") + " control bytes (NUL, backspace and "
                       "similar, which TeX refuses to read)")
    notes = []
    if removed:
        notes.append("This rendering removed " + " and ".join(removed) + ".")
    if tally["transliterated"]:
        notes.append("This fragment is engine-neutral, so it compiles under pdflatex as well "
                     "as XeLaTeX: " + format(tally["transliterated"], ",") + " characters were "
                     "transliterated (Greek to math or its name, arrows and box drawing to "
                     "ASCII).")
    if tally["hardwrapped"]:
        notes.append(format(tally["hardwrapped"], ",") + " very long lines were hard-wrapped "
                     "at " + str(_TEX_HARD_WRAP) + " characters so TeX could typeset them.")
    if tally["split_boxes"]:
        notes.append(format(tally["split_boxes"], ",") + " very large turn(s) were split into "
                     "consecutive boxes of at most " + format(_TEX_BOX_MAX_LINES, ",")
                     + " lines each, titled (part k/n), so TeX could hold them in memory; "
                     "nothing was omitted.")
    if notes:
        notes.append("The HTML archive holds all of it unaltered.")
        B[dropnote_slot] = inl(" ".join(notes)) + "\n\n"
    return "".join(B), tally


def compile_pdf(tex_path):
    """Two XeLaTeX passes: the second resolves the table of contents."""
    exe = shutil.which("xelatex")
    if not exe:
        sys.exit("xelatex not found on PATH -- required for --format pdf")
    for run in (1, 2):
        # xelatex writes font names and file paths in whatever encoding the OS
        # hands it; decoding that as the Windows default raises inside
        # subprocess's reader thread and buries the real result in a traceback.
        p = subprocess.run([exe, "-interaction=nonstopmode", "-halt-on-error",
                            tex_path.name], cwd=str(tex_path.parent),
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if p.returncode != 0:
            log = tex_path.with_suffix(".log")
            tail = ""
            if log.exists():
                tail = "\n".join(log.read_text(encoding="utf-8", errors="replace")
                                 .splitlines()[-30:])
            sys.exit("xelatex failed on pass " + str(run) + ":\n" + tail)
    for ext in (".aux", ".log", ".out", ".toc"):
        tex_path.with_suffix(ext).unlink(missing_ok=True)
    (tex_path.parent / "missfont.log").unlink(missing_ok=True)
    return tex_path.with_suffix(".pdf")


# ---------------------------------------------------------------------------
# claude.ai import
#
# claude.ai's data export (Settings -> Privacy -> Export data) ships a
# conversations.json in its own schema: a list of conversations, each with
# chat_messages carrying sender/text/content/attachments. The adapter converts
# one conversation into this tool's record model and lets the normal pipeline
# do everything else -- discovery, fidelity, all four formats -- unchanged.
# The export carries no usage data and no model name; the page says so.
# ---------------------------------------------------------------------------

CLAUDE_AI_MODEL = "claude.ai (model not in export)"


def claude_ai_records(conv: dict) -> list[dict]:
    sid = conv.get("uuid") or "claude-ai-import"
    name = conv.get("name") or sid
    msgs = conv.get("chat_messages") or []
    recs: list[dict] = [
        {"type": "ai-title", "aiTitle": name, "sessionId": sid},
        {"type": "attachment", "sessionId": sid, "uuid": f"{sid}-import-note",
         "timestamp": conv.get("created_at"),
         "attachment": {"type": "hook_system_message",
                        "hookName": "claude.ai import",
                        "content": (f"Imported from a claude.ai data export "
                                    f"(conversations.json): conversation "
                                    f"“{name}”, {len(msgs)} messages. "
                                    "The export records no token usage and no "
                                    "model name.")}},
    ]
    for i, msg in enumerate(msgs):
        if not isinstance(msg, dict):
            continue
        base = {"sessionId": sid, "uuid": msg.get("uuid") or f"{sid}-msg-{i}",
                "timestamp": msg.get("created_at") or conv.get("created_at"),
                "version": "claude.ai export"}
        text = msg.get("text") or ""
        content = msg.get("content")
        blocks = [b for b in content if isinstance(b, dict)] \
            if isinstance(content, list) else []

        if msg.get("sender") == "human":
            htext = text or "\n\n".join(
                b.get("text", "") for b in blocks if b.get("type") == "text")
            if htext.strip():
                recs.append({**base, "type": "user", "promptSource": "typed",
                             "origin": {"kind": "human"},
                             "message": {"role": "user", "content": htext}})
            for j, att in enumerate(msg.get("attachments") or []):
                if not isinstance(att, dict):
                    continue
                recs.append({**base, "uuid": f"{base['uuid']}-att-{j}",
                             "type": "attachment",
                             "attachment": {"type": "file",
                                            "filename": att.get("file_name", ""),
                                            "content": att.get("extracted_content")
                                            or f"({att.get('file_type', 'file')}; "
                                               "content not included in the export)"}})
            for j, f_ in enumerate(msg.get("files") or []):
                if not isinstance(f_, dict):
                    continue
                recs.append({**base, "uuid": f"{base['uuid']}-file-{j}",
                             "type": "attachment",
                             "attachment": {"type": "file",
                                            "filename": f_.get("file_name", ""),
                                            "content": "(binary file; content not "
                                                       "included in claude.ai exports)"}})
            continue

        # Assistant. tool_result blocks belong to user records in the Claude
        # Code model, so split the stream there and the tool call still folds.
        if not blocks and text:
            blocks = [{"type": "text", "text": text}]
        pending: list[dict] = []
        part = 0

        def flush(kind_blocks, rtype):
            nonlocal part
            if not kind_blocks:
                return
            rec = {**base, "uuid": f"{base['uuid']}-p{part}" if part else base["uuid"],
                   "type": rtype,
                   "message": ({"role": "assistant", "model": CLAUDE_AI_MODEL,
                                "content": list(kind_blocks)} if rtype == "assistant"
                               else {"role": "user", "content": list(kind_blocks)})}
            recs.append(rec)
            part += 1

        for b in blocks:
            if b.get("type") == "tool_result":
                flush(pending, "assistant")
                pending = []
                flush([b], "user")
            else:
                pending.append(b)
        flush(pending, "assistant")
    return recs


def load_claude_ai_export(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        data = data.get("conversations") or [data]
    return [c for c in data if isinstance(c, dict) and c.get("chat_messages") is not None]


# ---------------------------------------------------------------------------
# Index mode
# ---------------------------------------------------------------------------

def is_legacy_version(v) -> bool:
    """v1 archives carry no usable metadata; anything from 2.0 on does.
    Compare the major number, not the first character -- '3.0' is not v1."""
    try:
        return int(str(v).split(".")[0]) < 2
    except (ValueError, TypeError):
        return True


def _age_label(seconds: float) -> str:
    if seconds < 90:
        return "now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"


_HUMAN_TURN_RE = re.compile(
    r'<section class="turn human-turn" id="([^"]+)"[^>]*>.*?'
    r'<span class="who">Human(?: <span class="rtag" id="([^"]+)">[^<]*</span>)?</span>.*?'
    r'<div class="turn-body"><div class="raw(?: mono)?">(.*?)</div></div>', re.S)
_SEARCH_TEXT_CAP = 400


def prompt_index_entry(archive_dir: Path, meta: dict) -> dict:
    """Every human prompt of one archive, with a deep link, for the index
    page's cross-archive search. Read back from the archive's own HTML (all
    pages of a paginated one), so archives written by earlier versions and
    imports are covered alike; prompts without a P tag link to their turn."""
    prompts: list[dict] = []
    for page_name in (meta.get("pages") or [meta["file"]]):
        pf = archive_dir / page_name
        try:
            text = pf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for anchor, tag, body in _HUMAN_TURN_RE.findall(text):
            plain = html.unescape(re.sub(r"<[^>]+>", "", body))
            plain = " ".join(plain.split())
            if not plain:
                continue
            prompts.append({"tag": tag or "", "href": f"{page_name}#{tag or anchor}",
                            "text": plain[:_SEARCH_TEXT_CAP]})
    return {"session_id": meta.get("session_id", ""), "title": meta.get("title") or "",
            "file": meta["file"], "prompts": prompts}


def build_index(archive_dir: Path, projects_root: Path, out_path: Path,
                sessions: dict | None = None, refresh: int | None = None) -> None:
    if sessions is None:
        sessions = scan_sessions(projects_root)
    now = datetime.datetime.now(datetime.timezone.utc)
    # A first --index into a fresh directory must simply create it, as an
    # export does; the archive is empty, not an error.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    archived: dict[str, dict] = {}
    for f in sorted(archive_dir.glob("*.html")):
        if f.name == out_path.name:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r'<script type="application/json" id="archive-meta">(.*?)</script>', text, re.S)
        meta = {}
        if m:
            try:
                meta = json.loads(m.group(1))
            except json.JSONDecodeError:
                meta = {}
        if not meta:
            sid = f.name.split("_")[0]
            meta = {"session_id": sid, "title": f.stem, "archiver_version": "1.x (no metadata)"}
        if meta.get("continuation_of"):
            continue                     # page 2+ of a paginated archive
        meta["file"] = f.name
        meta["size_mb"] = f.stat().st_size / 1e6
        archived[meta["session_id"]] = meta

    rows = []
    for sid, info in sorted(sessions.items(), key=lambda kv: (kv[1].last or ""), reverse=True):
        meta = archived.get(sid)
        chain_best, related = resolve_chain(sid, sessions)
        covered_by = None
        covered_dropped = 0
        if not meta:
            for r in related:
                if r["session_id"] in archived and r["relation"] == "superset":
                    covered_by = r["session_id"]
                    covered_dropped = r.get("dropped", 0)
                    break
        # Match the archive pages, which print local time; sort on the raw UTC ISO.
        def _local(iso):
            if not iso:
                return ""
            try:
                return fmt_local(parse_ts(iso))
            except ValueError:
                return iso[:19].replace("T", " ")
        last = _local(info.last)
        started = _local(info.first)
        duration = ""
        if info.first and info.last:
            try:
                t0 = datetime.datetime.fromisoformat(info.first.replace("Z", "+00:00"))
                t1 = datetime.datetime.fromisoformat(info.last.replace("Z", "+00:00"))
                mins = max(0, int((t1 - t0).total_seconds() // 60))
                duration = f"{mins // 60}h {mins % 60:02d}m" if mins >= 60 else f"{mins}m"
            except ValueError:
                duration = ""
        if meta:
            legacy = is_legacy_version(meta.get("archiver_version", ""))
            stale = bool(meta.get("last_record") and info.last and meta["last_record"][:19] < info.last[:19])
            if legacy:
                status = '<span class="pill stale">legacy v1</span>'
            elif stale:
                status = '<span class="pill stale">stale</span>'
            else:
                status = '<span class="pill ok">archived</span>'
            link = f'<a href="{esc(meta["file"])}">{esc(meta.get("title") or sid)}</a>'
            if legacy:
                detail = ('written by the v1 archiver &mdash; no embedded metadata, and its counts '
                          'and token figures are known to be wrong. Re-run to replace it.')
            else:
                # Metadata is read back from files on disk, so a field may be
                # absent or hand-edited; never let one entry abort the index.
                def _n(key, spec=","):
                    v = meta.get(key)
                    return format(v, spec) if isinstance(v, (int, float)) else "?"
                # The meter's figure is shown only when it covers the whole
                # session; otherwise the list-price estimate is the honest one.
                metered = (isinstance(meta.get("reported_cost_usd"), (int, float))
                           and meta.get("reported_cost_partial") is False)
                cost_txt = (f'${_n("reported_cost_usd", ",.2f")} reported' if metered
                            else f'${_n("list_cost_usd", ",.2f")} at list price')
                detail = (f'{_n("records")} records &middot; {_n("tool_calls")} tool calls &middot; '
                          f'{cost_txt} &middot; {meta["size_mb"]:.1f} MB &middot; '
                          f'archiver v{meta.get("archiver_version")}')
        elif covered_by:
            status = '<span class="pill covered">covered</span>'
            link = esc(info.title or sid)
            detail = f'continued into <code>{esc(covered_by[:8])}</code>, archived there'
            if covered_dropped:
                detail += (f' &middot; {covered_dropped} record(s) not carried over '
                           '(bookkeeping only)')
        else:
            status = '<span class="pill missing">not archived</span>'
            link = esc(info.title or sid)
            detail = f"{info.records:,} records on disk"
            if info.subagents:
                detail += f" &middot; {info.subagents} subagent transcript(s)"
        if info.source != "claude-code":
            detail += f" &middot; source: {esc(info.source)}"
        status_key = re.sub(r"<[^>]+>", "", status).strip()
        title_key = re.sub(r"<[^>]+>", "", link).strip().lower()
        # Activity: computed at generation time, then left to decay in the
        # browser -- the page's JS recomputes the age from data-ts, so a
        # session can only go quiet on screen, never freshly "active", until
        # the index is regenerated (see --watch).
        age = None
        if info.last:
            try:
                age = (now - parse_ts(info.last)).total_seconds()
            except ValueError:
                age = None
        if age is None:
            act_cell = '<td class="activity" data-k="~"></td>'
        else:
            cls = "act" if age < 600 else "quiet"
            dot = "&#9679; " if age < 600 else ""
            act_cell = (f'<td class="activity" data-ts="{esc(info.last)}" '
                        f'data-k="{esc(info.last)}">'
                        f'<span class="pill {cls}">{dot}{_age_label(age)}</span></td>')
        rows.append(
            f'<tr><td data-k="{esc(status_key)}">{status}</td>'
            + act_cell +
            f'<td data-k="{esc(sid)}"><code>{esc(sid[:8])}</code></td>'
            f'<td data-k="{esc(title_key)}">{link}<div class="muted small">{detail}</div></td>'
            f'<td class="num" data-k="{esc(info.first or "")}" title="{esc((info.first or "")[:19])} UTC">{esc(started)}'
            f'<div class="muted small">{esc(duration)}</div></td>'
            f'<td class="num" data-k="{esc(info.last or "")}" title="{esc((info.last or "")[:19])} UTC">{esc(last)}</td></tr>')

    # Archives whose source is not a session on disk: claude.ai imports, or
    # sessions whose transcript has since been deleted. They are still part of
    # the archive and belong on its index.
    n_imported = 0
    for sid, meta in sorted(archived.items(),
                            key=lambda kv: kv[1].get("last_record") or "", reverse=True):
        if sid in sessions:
            continue
        n_imported += 1
        kind = meta.get("source_kind") or "source transcript not on disk"
        link = f'<a href="{esc(meta["file"])}">{esc(meta.get("title") or sid)}</a>'
        detail = (f'{meta.get("records", "?")} records &middot; {meta["size_mb"]:.1f} MB '
                  f'&middot; archiver v{esc(str(meta.get("archiver_version")))} '
                  f'&middot; source: {esc(str(kind))}')
        title_key = re.sub(r"<[^>]+>", "", link).strip().lower()

        def _loc(iso):
            try:
                return fmt_local(parse_ts(iso)) if iso else ""
            except ValueError:
                return str(iso)[:19].replace("T", " ")
        rows.append(
            f'<tr><td data-k="archived"><span class="pill ok">archived</span></td>'
            '<td class="activity" data-k="~"></td>'
            f'<td data-k="{esc(sid)}"><code>{esc(sid[:8])}</code></td>'
            f'<td data-k="{esc(title_key)}">{link}<div class="muted small">{detail}</div></td>'
            f'<td class="num" data-k="{esc(meta.get("started") or "")}">{esc(_loc(meta.get("started")))}</td>'
            f'<td class="num" data-k="{esc(meta.get("last_record") or "")}">{esc(_loc(meta.get("last_record")))}</td></tr>')

    counts = Counter()
    for sid in sessions:
        if sid in archived:
            counts["archived"] += 1
        else:
            counts["missing"] += 1
    search_index = [prompt_index_entry(archive_dir, meta)
                    for _sid, meta in sorted(archived.items(),
                                             key=lambda kv: kv[1].get("last_record") or "",
                                             reverse=True)]
    n_prompts = sum(len(e["prompts"]) for e in search_index)
    page = _INDEX_TEMPLATE.format(
        rows="".join(rows),
        search_json=json.dumps(search_index, ensure_ascii=False).replace("</", "<\\/"),
        n_prompts=f"{n_prompts:,}",
        summary=(f"{len(sessions)} sessions on disk &middot; {counts['archived']} archived &middot; "
                 f"{counts['missing']} not archived directly"
                 + (f" &middot; {n_imported} archived from imports or deleted sources"
                    if n_imported else "")),
        generated=esc(fmt_local(datetime.datetime.now(datetime.timezone.utc))),
        refresh_meta=(f'<meta http-equiv="refresh" content="{int(refresh)}">\n'
                      if refresh else ""),
        css=_CSS,
        index_css=_INDEX_CSS,
        index_js=_INDEX_JS,
    )
    out_path.write_text(page, encoding="utf-8")
    CON.say(f"wrote {out_path} ({len(sessions)} sessions, {counts['archived']} archived"
            + (f", {n_imported} imported" if n_imported else "") + ")")


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

_CSS = """
:root{
  --paper:#faf7f0; --ink:#22221f; --ink-soft:#5d5b53; --ink-faint:#8d8a7f;
  --line:#dcd9cf; --line-soft:#ebe8e0; --card:#fffdf8; --code-bg:#eeebe2;
  --human:#2f6f4f; --human-bg:#e9f3ed;
  --claude:#44578c; --claude-bg:#eceff8;
  --think:#6b5b95; --think-bg:#f0ecf6;
  --system:#96762c; --system-bg:#f7efdd;
  --harness:#6f6a62; --harness-bg:#f1efe8;
  --tool:#5c5750; --tool-bg:#f0eee7;
  --error:#a33f2f; --error-bg:#fbeae6;
  --shadow:0 1px 2px rgba(20,20,15,.05), 0 2px 10px rgba(20,20,15,.04);
  --bubble:0 1px 2px rgba(20,20,15,.06), 0 3px 12px rgba(20,20,15,.05);
}
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]){
  --paper:#14140f; --ink:#e9e6dc; --ink-soft:#a29c8c; --ink-faint:#7d7768;
  --line:#332f25; --line-soft:#252219; --card:#1b1914; --code-bg:#201e17;
  --human:#7fc79f; --human-bg:#17251f;
  --claude:#9db0e8; --claude-bg:#191d2b;
  --think:#b8a6e0; --think-bg:#201b2b;
  --system:#e0b95a; --system-bg:#231e10;
  --harness:#a29c8c; --harness-bg:#1d1b15;
  --tool:#a29c8c; --tool-bg:#1d1b15;
  --error:#e08a76; --error-bg:#2a1712;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 2px 14px rgba(0,0,0,.35);
  --bubble:0 1px 2px rgba(0,0,0,.45), 0 3px 16px rgba(0,0,0,.3);
}}
:root[data-theme="dark"]{
  --paper:#14140f; --ink:#e9e6dc; --ink-soft:#a29c8c; --ink-faint:#7d7768;
  --line:#332f25; --line-soft:#252219; --card:#1b1914; --code-bg:#201e17;
  --human:#7fc79f; --human-bg:#17251f;
  --claude:#9db0e8; --claude-bg:#191d2b;
  --think:#b8a6e0; --think-bg:#201b2b;
  --system:#e0b95a; --system-bg:#231e10;
  --harness:#a29c8c; --harness-bg:#1d1b15;
  --tool:#a29c8c; --tool-bg:#1d1b15;
  --error:#e08a76; --error-bg:#2a1712;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 2px 14px rgba(0,0,0,.35);
  --bubble:0 1px 2px rgba(0,0,0,.45), 0 3px 16px rgba(0,0,0,.3);
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font-family:"Segoe UI",system-ui,-apple-system,sans-serif;font-size:15.5px;line-height:1.62}
code,pre,.mono{font-family:"Cascadia Code","JetBrains Mono","SF Mono",Consolas,monospace}
a{color:var(--claude)}
.layout{display:grid;grid-template-columns:308px 1fr;max-width:1500px;margin:0 auto;min-height:100vh}
@media (max-width:960px){.layout{grid-template-columns:1fr}.sidebar{position:relative;height:auto}}
.sidebar{position:sticky;top:0;height:100vh;overflow-y:auto;border-right:1px solid var(--line);
  padding:20px 16px;background:var(--card)}
.sidebar h2{font-size:10.5px;letter-spacing:.11em;text-transform:uppercase;color:var(--ink-faint);
  margin:20px 0 8px;font-weight:700}
.session-info{font-size:12.5px;margin:0}
.session-info dt{color:var(--ink-soft);margin-top:7px}
.session-info dd{margin:0;font-family:"Cascadia Code","JetBrains Mono",monospace;font-size:12px;word-break:break-word}
.controls{display:flex;flex-direction:column;gap:7px}
.controls input[type=search]{font:inherit;font-size:13px;padding:7px 9px;border-radius:7px;
  border:1px solid var(--line);background:var(--paper);color:var(--ink);width:100%}
.toggles{display:flex;flex-wrap:wrap;gap:5px}
.toggles label{font-size:11.5px;display:inline-flex;align-items:center;gap:4px;padding:3px 7px;
  border:1px solid var(--line);border-radius:20px;cursor:pointer;user-select:none;color:var(--ink-soft)}
.toggles label:hover{background:var(--line-soft)}
.toggles input{margin:0}
.btnrow{display:flex;gap:6px}
.btnrow button{flex:1;font:inherit;font-size:11.5px;padding:5px 8px;border-radius:6px;
  border:1px solid var(--line);background:var(--paper);color:var(--ink);cursor:pointer}
.btnrow button:hover{background:var(--line-soft)}
.toc{display:flex;flex-direction:column;gap:2px;font-size:12.5px}
.toc-item{padding:5px 8px;border-radius:6px;text-decoration:none;color:var(--ink);
  border-left:3px solid transparent;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.toc-item:hover{background:var(--line-soft)}
.toc-item.toc-human{border-left-color:var(--human);font-weight:600}
.toc-item.toc-system{border-left-color:var(--system);color:var(--ink-soft);font-size:11.5px}
.toc-item.toc-key{border-left-color:var(--claude);font-weight:700}
.toc-item.hidden{display:none}
.main{padding:30px 40px 120px;max-width:940px}
@media (max-width:760px){
  .human-turn{margin-left:0}
  .assistant-turn{margin-right:0}
}
header.mast{margin-bottom:28px;padding-bottom:18px;border-bottom:1px solid var(--line)}
header.mast h1{font-size:25px;margin:0 0 6px}
header.mast p{color:var(--ink-soft);margin:0;font-size:13.5px}
.turn{margin-bottom:12px}
.turn.filtered,.turn.unmatched{display:none}
.search-count{font-size:11px;color:var(--ink-faint);min-height:1em}
.turn-label{display:flex;align-items:center;gap:9px;margin-bottom:5px;font-size:12.5px;flex-wrap:wrap}
.turn-label .who{font-weight:700;font-family:"Cascadia Code","JetBrains Mono",monospace}
.rtag{font-size:10px;font-weight:700;padding:1px 6px;border-radius:9px;background:var(--code-bg);
  color:var(--ink-soft);letter-spacing:.04em;vertical-align:1px}
.turn-label .ts{color:var(--ink-faint);margin-left:auto;font-family:"Cascadia Code",monospace;font-size:11px}
.badge{font-size:10.5px;padding:1px 7px;border-radius:10px;background:var(--system-bg);color:var(--system)}
.badge.side{background:var(--claude-bg);color:var(--claude)}
.evidence{font-size:10.5px;color:var(--ink-faint);font-family:"Cascadia Code",monospace}
/* Chat layout: what you typed sits right, Claude answers from the left, the
   way a messaging app reads. Tool, system and harness turns stay full width --
   they are machinery, not dialogue, and indenting them would imply a speaker. */
.human-turn{margin-left:16%}
.human-turn .turn-label{flex-direction:row-reverse}
.human-turn .turn-label .ts{margin-left:0;margin-right:auto}
.human-turn .turn-label .who{color:var(--human)}
.human-turn .turn-body{background:var(--human-bg);border:1.5px solid var(--human);
  border-radius:12px 12px 4px 12px;padding:12px 16px;box-shadow:var(--bubble)}
/* Verbatim: what you typed or pasted, newlines and all. */
.human-turn .raw{white-space:pre-wrap;word-break:break-word}
.human-turn .raw.mono{font-family:"Cascadia Code","JetBrains Mono","SF Mono",Consolas,monospace;
  font-size:12.8px;line-height:1.5}
.assistant-turn{margin-right:10%}
.assistant-turn .turn-label .who{color:var(--claude)}
.assistant-turn .turn-body{background:var(--claude-bg);border:1.5px solid var(--claude);
  border-radius:12px 12px 12px 4px;padding:12px 16px;box-shadow:var(--bubble)}
.assistant-turn .turn-body>*:first-child{margin-top:0}
.assistant-turn .turn-body>*:last-child{margin-bottom:0}
.thinking-turn details{background:var(--think-bg);border-left:3px solid var(--think);
  border-radius:0 8px 8px 0}
.thinking-turn summary{cursor:pointer;padding:6px 14px;list-style:none;display:flex;gap:9px;
  align-items:center;font-size:12.5px}
.thinking-turn summary::-webkit-details-marker{display:none}
.thinking-turn summary::before{content:"\\25B8";color:var(--think)}
.thinking-turn details[open] summary::before{content:"\\25BE"}
.thinking-turn .who{color:var(--think);font-weight:700;font-family:"Cascadia Code",monospace}
.thinking-turn .turn-body{padding:2px 16px 12px;font-size:14.5px;color:var(--ink-soft)}
.system-turn .turn-label .who,.event-turn .turn-label .who{color:var(--system)}
.tool-turn>details{border:1px solid var(--line);border-radius:9px;overflow:hidden}
.system-turn .turn-body,.event-turn .turn-body{border:1px solid var(--line);
  border-radius:9px;background:var(--system-bg);
  border-left:3px solid var(--system);border-radius:0 8px 8px 0;padding:6px 14px}
.system-turn summary{cursor:pointer;font-size:12.5px;color:var(--ink-soft)}
.system-turn pre,.event-turn pre{font-size:11.5px;max-height:340px;overflow:auto}
.harness-turn details{background:var(--harness-bg);border:1px dashed var(--line);border-radius:7px}
.harness-turn summary{cursor:pointer;padding:5px 12px;font-size:12px;color:var(--ink-soft);
  list-style:none;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.harness-turn summary::-webkit-details-marker{display:none}
.harness-turn .io{padding:0 12px 10px}
.harness-turn pre{font-size:11.5px;max-height:400px;overflow:auto}
.tool-turn{margin-bottom:7px}
.tool-turn details{background:var(--tool-bg);border:1px solid var(--line);border-radius:8px}
.tool-turn.tool-error details{background:var(--error-bg);border-color:var(--error)}
.tool-turn.tool-pending details{border-style:dashed}
.tool-turn summary{cursor:pointer;padding:7px 13px;font-size:13px;list-style:none;
  display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.tool-turn summary::-webkit-details-marker{display:none}
.tool-turn summary::before{content:"\\25B8";color:var(--ink-faint);flex:0 0 auto}
.tool-turn details[open] summary::before{content:"\\25BE"}
.tool-turn summary code{background:none;padding:0;color:var(--ink-soft);overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap;min-width:0}
.chip{font-family:"Cascadia Code","JetBrains Mono",monospace;font-size:10.5px;font-weight:700;
  letter-spacing:.03em;padding:2px 7px;border-radius:5px;background:var(--code-bg);
  color:var(--tool);flex:0 0 auto}
.harness-chip{background:var(--code-bg);color:var(--harness)}
.tool-turn.tool-error .chip{background:var(--error-bg);color:var(--error)}
.io{padding:0 13px 13px;display:grid;gap:9px}
.io-label{font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-faint);margin-bottom:3px}
.io-block pre{margin:0}
pre.plain,pre.code-block{background:var(--code-bg);border:1px solid var(--line);border-radius:6px;
  padding:9px 12px;overflow-x:auto;font-size:12.5px;line-height:1.5;margin:9px 0;
  white-space:pre-wrap;word-break:break-word;max-height:640px;overflow-y:auto}
code{background:var(--code-bg);padding:1px 5px;border-radius:4px;font-size:.9em}
pre code{background:none;padding:0}
img{max-width:100%;border:1px solid var(--line);border-radius:6px}
.summary-turn,.report-turn,.usage-turn{margin-bottom:26px}
.summary-turn .who,.report-turn .who,.usage-turn .who{color:var(--ink);font-size:11px;
  letter-spacing:.08em;text-transform:uppercase}
.summary-body,.report-body,.usage-body{background:var(--card);border:1px solid var(--line);
  border-left:4px solid var(--claude);border-radius:0 10px 10px 0;padding:6px 22px 16px;box-shadow:var(--shadow)}
.report-body{border-left-color:var(--system)}
.usage-body{border-left-color:var(--human)}
.summary-body h3,.report-body h3{font-size:12.5px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--claude);margin:18px 0 8px}
.report-body h4{font-size:11.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--ink-soft);
  margin:16px 0 6px}
.report-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}
@media (max-width:760px){.report-grid{grid-template-columns:1fr}}
.table-wrap{overflow-x:auto;margin:9px 0}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border:1px solid var(--line);padding:4px 9px;text-align:left;vertical-align:top}
th{background:var(--code-bg);font-size:11.5px}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;
  font-family:"Cascadia Code",monospace;font-size:12px}
table.mini{font-size:12px}
table.mini td{padding:2px 8px}
table.usage td{font-size:12.5px}
table.usage tr.total td{font-weight:700;background:var(--line-soft)}
.callout{border-left:3px solid var(--system);background:var(--system-bg);border-radius:0 8px 8px 0;
  padding:10px 16px;margin:14px 0;font-size:13.5px}
.callout ul{margin:6px 0 0;padding-left:20px}
.muted{color:var(--ink-soft)}
.small{font-size:12px}
blockquote{border-left:3px solid var(--line);margin:9px 0;padding:2px 14px;color:var(--ink-soft)}
ul,ol{margin:8px 0;padding-left:22px}
li{margin:3px 0}
h1,h2,h3,h4,h5,h6{margin:15px 0 7px;line-height:1.3}
hr{border:none;border-top:1px solid var(--line);margin:16px 0}
del{opacity:.65}
.subagent-block>details{background:var(--card);border:1px solid var(--line);
  border-left:4px solid var(--claude);border-radius:0 10px 10px 0;box-shadow:var(--shadow)}
.subagent-block>details>summary{cursor:pointer;padding:9px 14px;font-size:13px;list-style:none;
  display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.subagent-block>details>summary::-webkit-details-marker{display:none}
.subagent-block>details>summary::before{content:"\\25B8";color:var(--ink-faint)}
.subagent-block>details[open]>summary::before{content:"\\25BE"}
.subagent-body{padding:4px 14px 14px;border-top:1px dashed var(--line)}
.page-nav{display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:13px;
  padding:8px 14px;margin:0 0 18px;border:1px solid var(--line);border-radius:9px;
  background:var(--card);color:var(--ink-soft)}
.page-nav a{text-decoration:none}
.page-nav strong{color:var(--ink)}
.pill{font-size:10.5px;padding:2px 8px;border-radius:11px;font-weight:700;white-space:nowrap}
.pill.ok{background:var(--human-bg);color:var(--human)}
.pill.act{background:var(--human-bg);color:var(--human);animation:actpulse 2.4s ease-in-out infinite}
.pill.quiet{background:var(--line-soft);color:var(--ink-faint);font-weight:600}
@keyframes actpulse{0%,100%{opacity:1}50%{opacity:.55}}
.pill.stale{background:var(--system-bg);color:var(--system)}
.pill.covered{background:var(--claude-bg);color:var(--claude)}
.pill.missing{background:var(--error-bg);color:var(--error)}
"""

_JS = """
(function(){
  /* Theme: follow the OS unless the reader chose; the choice is remembered
     per browser in localStorage (wrapped: storage can be unavailable). */
  var root = document.documentElement;
  var themeBtn = document.getElementById('theme-toggle');
  function currentDark(){
    var t = root.getAttribute('data-theme');
    if (t) return t === 'dark';
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  }
  function applyTheme(t){
    if (t) root.setAttribute('data-theme', t); else root.removeAttribute('data-theme');
    if (themeBtn) themeBtn.textContent = currentDark() ? 'Light theme' : 'Dark theme';
  }
  try { applyTheme(localStorage.getItem('archive-theme') || ''); } catch (e) { applyTheme(''); }
  if (themeBtn) themeBtn.addEventListener('click', function(){
    var next = currentDark() ? 'light' : 'dark';
    applyTheme(next);
    try { localStorage.setItem('archive-theme', next); } catch (e) {}
  });

  /* Turn search: hide every turn whose text does not contain the query.
     Lead sections (summary, usage, fidelity) always stay. */
  var search = document.getElementById('search');
  var count = document.getElementById('search-count');
  if (search) search.addEventListener('input', function(){
    var q = search.value.toLowerCase();
    var shown = 0, total = 0;
    document.querySelectorAll('.turn').forEach(function(el){
      if (el.classList.contains('summary-turn') || el.classList.contains('usage-turn')
          || el.classList.contains('report-turn')) return;
      total++;
      var hit = q === '' || el.textContent.toLowerCase().indexOf(q) !== -1;
      el.classList.toggle('unmatched', !hit);
      if (hit) shown++;
    });
    if (count) count.textContent = q === '' ? '' : shown + ' of ' + total + ' turns match';
  });

  var lanes = ['thinking','tool','harness','system','subagent'];
  lanes.forEach(function(lane){
    var box = document.getElementById('lane-' + lane);
    if (!box) return;
    box.addEventListener('change', function(){
      document.querySelectorAll('.turn[data-lane="' + lane + '"]').forEach(function(el){
        el.classList.toggle('filtered', !box.checked);
      });
    });
  });
  var expand = document.getElementById('expand-all');
  var collapse = document.getElementById('collapse-all');
  if (expand) expand.addEventListener('click', function(){
    document.querySelectorAll('.turn details').forEach(function(d){ d.open = true; });
  });
  if (collapse) collapse.addEventListener('click', function(){
    document.querySelectorAll('.turn details').forEach(function(d){ d.open = false; });
  });
  var search = document.getElementById('filter');
  if (search) search.addEventListener('input', function(){
    var q = search.value.toLowerCase();
    document.querySelectorAll('.toc-item').forEach(function(a){
      if (a.classList.contains('toc-key')) return;
      a.classList.toggle('hidden', q !== '' && a.textContent.toLowerCase().indexOf(q) === -1);
    });
  });
  function jump(dir){
    var anchors = Array.prototype.slice.call(
      document.querySelectorAll('.human-turn[id], .system-turn[id], .event-turn[id]'))
      .filter(function(el){ return !el.classList.contains('filtered'); });
    if (!anchors.length) return;
    var y = window.scrollY + 8, target = null;
    if (dir > 0) { for (var i=0;i<anchors.length;i++){ if (anchors[i].offsetTop > y + 4){ target = anchors[i]; break; } } }
    else { for (var j=anchors.length-1;j>=0;j--){ if (anchors[j].offsetTop < y - 4){ target = anchors[j]; break; } } }
    if (target) window.scrollTo({top: target.offsetTop - 8, behavior: 'smooth'});
  }
  document.addEventListener('keydown', function(e){
    if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
    if (e.key === 'j') { jump(1); e.preventDefault(); }
    if (e.key === 'k') { jump(-1); e.preventDefault(); }
    if (e.key === '/') { var s = document.getElementById('filter'); if (s) { s.focus(); e.preventDefault(); } }
  });
})();
"""

_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title} — Session Transcript</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>{css}</style>
</head>
<body>
<script type="application/json" id="archive-meta">{meta_json}</script>
<div class="layout">
  <nav class="sidebar">
    <div class="controls">
      <input type="search" id="search" placeholder="Search turns" aria-label="Search turns">
      <div class="search-count" id="search-count"></div>
      <input type="search" id="filter" placeholder="Filter contents  ( / )" aria-label="Filter contents">
      <div class="toggles">
        <label><input type="checkbox" id="lane-thinking" checked> thinking</label>
        <label><input type="checkbox" id="lane-tool" checked> tools</label>
        <label><input type="checkbox" id="lane-harness" checked> harness</label>
        <label><input type="checkbox" id="lane-system" checked> events</label>
        <label><input type="checkbox" id="lane-subagent" checked> subagents</label>
      </div>
      <div class="btnrow">
        <button id="expand-all" type="button">Expand all</button>
        <button id="collapse-all" type="button">Collapse all</button>
        <button id="theme-toggle" type="button">Dark theme</button>
      </div>
    </div>
    <h2>Session</h2>
    <dl class="session-info">{session_info}</dl>
    <h2>Contents</h2>
    <div class="toc">{toc_html}</div>
  </nav>
  <main class="main">
    <header class="mast">
      <h1>{title}</h1>
      <p>{subtitle}</p>
      <p class="muted small">Timestamps are local; hover for UTC. <kbd>j</kbd>/<kbd>k</kbd> jump between
         human turns, <kbd>/</kbd> filters the contents list, the search box hides turns that do not
         match. Thinking, tool I/O and harness events are collapsed &mdash; use the toggles to hide a
         lane entirely.</p>
    </header>
    {page_nav}
    {lead_html}
    {body_html}
    {page_nav}
  </main>
</div>
<script>{js}</script>
</body>
</html>
"""

_INDEX_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Claude Code session archive</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
{refresh_meta}<style>{css}
{index_css}
</style>
</head>
<body>
<div class="layout"><main class="main">
<header class="mast">
  <h1>Claude Code session archive</h1>
  <p>{summary}</p>
  <p class="muted small">Generated {generated}. &ldquo;Covered&rdquo; means the session was resumed into
     another transcript that <em>is</em> archived, so its records live in that file.</p>
</header>
<div class="archive-search">
  <input type="search" id="archive-search" placeholder="Search every prompt across all archives ({n_prompts} prompts)"
         aria-label="Search prompts across all archives">
  <div class="muted small" id="search-status"></div>
  <div id="search-results" class="search-results" hidden></div>
</div>
<script type="application/json" id="search-index">{search_json}</script>
<div class="table-wrap"><table>
<thead><tr><th class="sortable" data-i="0">status</th>
<th class="sortable" data-i="1">activity</th>
<th class="sortable" data-i="2">id</th>
<th class="sortable" data-i="3">session</th>
<th class="sortable num" data-i="4">started</th>
<th class="sortable num sorted-desc" data-i="5">last record</th></tr></thead>
<tbody>{rows}</tbody>
</table></div>
</main></div>
<script>{index_js}</script>
</body>
</html>
"""

_INDEX_JS = """
(function () {
  /* Activity ages decay live: recompute from data-ts once a minute. The page
     cannot see new records without regeneration (see --watch), so a session
     can only go quiet on screen, never freshly active. */
  function ageLabel(s) {
    if (s < 90) return 'now';
    if (s < 3600) return Math.floor(s / 60) + 'm';
    if (s < 86400) return Math.floor(s / 3600) + 'h';
    return Math.floor(s / 86400) + 'd';
  }
  function tick() {
    document.querySelectorAll('td.activity[data-ts]').forEach(function (td) {
      var t = Date.parse(td.getAttribute('data-ts'));
      if (isNaN(t)) return;
      var s = (Date.now() - t) / 1000;
      var pill = td.querySelector('.pill');
      if (!pill) return;
      var active = s < 600;
      pill.className = 'pill ' + (active ? 'act' : 'quiet');
      pill.innerHTML = (active ? '\\u25CF ' : '') + ageLabel(s);
    });
  }
  tick();
  setInterval(tick, 60000);

  /* Cross-archive search: every human prompt of every archive is embedded
     as JSON at index time (see prompt_index_entry); matches deep-link to
     the prompt's anchor on its page, and the session table narrows to the
     sessions that matched. */
  var idxEl = document.getElementById('search-index');
  var box = document.getElementById('archive-search');
  var out = document.getElementById('search-results');
  var status = document.getElementById('search-status');
  var entries = [];
  try { entries = JSON.parse(idxEl ? idxEl.textContent : '[]'); } catch (e) { entries = []; }
  function escapeHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function snippet(text, q) {
    var i = text.toLowerCase().indexOf(q), a = Math.max(0, i - 70), b = Math.min(text.length, i + q.length + 90);
    return (a > 0 ? '\\u2026' : '') + escapeHtml(text.slice(a, i)) + '<mark>' + escapeHtml(text.slice(i, i + q.length))
      + '</mark>' + escapeHtml(text.slice(i + q.length, b)) + (b < text.length ? '\\u2026' : '');
  }
  function narrowTable(sids) {
    document.querySelectorAll('table tbody tr').forEach(function (tr) {
      var cell = tr.cells[2];
      var sid = cell ? (cell.getAttribute('data-k') || '') : '';
      tr.hidden = sids !== null && !sids[sid];
    });
  }
  if (box) box.addEventListener('input', function () {
    var q = box.value.trim().toLowerCase();
    if (q.length < 2) { out.hidden = true; out.innerHTML = ''; status.textContent = ''; narrowTable(null); return; }
    var hits = [], sids = {}, total = 0;
    entries.forEach(function (e) {
      var inTitle = e.title.toLowerCase().indexOf(q) !== -1;
      e.prompts.forEach(function (p) {
        if (p.text.toLowerCase().indexOf(q) !== -1) {
          total++; sids[e.session_id] = true;
          if (hits.length < 200) hits.push({e: e, p: p});
        }
      });
      if (inTitle) sids[e.session_id] = true;
    });
    status.textContent = total + ' matching prompt' + (total === 1 ? '' : 's') + ' in '
      + Object.keys(sids).length + ' session' + (Object.keys(sids).length === 1 ? '' : 's')
      + (total > 200 ? ' (first 200 shown)' : '');
    out.innerHTML = hits.map(function (h) {
      return '<a class="hit" href="' + escapeHtml(h.p.href) + '"><span class="hit-meta"><code>'
        + escapeHtml(h.e.session_id.slice(0, 8)) + '</code> ' + (h.p.tag ? '<span class="rtag">' + escapeHtml(h.p.tag) + '</span> ' : '')
        + escapeHtml(h.e.title) + '</span><span class="hit-text">' + snippet(h.p.text, q) + '</span></a>';
    }).join('');
    out.hidden = hits.length === 0;
    narrowTable(sids);
  });

  var table = document.querySelector('table');
  if (!table) return;
  var tbody = table.tBodies[0];
  var heads = table.querySelectorAll('th.sortable');
  function key(row, i) {
    var cell = row.cells[i];
    return cell ? (cell.getAttribute('data-k') || cell.textContent).trim().toLowerCase() : '';
  }
  heads.forEach(function (th) {
    th.addEventListener('click', function () {
      var i = +th.getAttribute('data-i');
      var desc = !th.classList.contains('sorted-desc');
      heads.forEach(function (h) { h.classList.remove('sorted-asc', 'sorted-desc'); });
      th.classList.add(desc ? 'sorted-desc' : 'sorted-asc');
      var rows = Array.prototype.slice.call(tbody.rows);
      rows.sort(function (a, b) {
        var x = key(a, i), y = key(b, i);
        if (x === y) return 0;
        if (x === '') return 1;          /* blanks always last */
        if (y === '') return -1;
        return (x < y ? -1 : 1) * (desc ? -1 : 1);
      });
      rows.forEach(function (r) { tbody.appendChild(r); });
    });
  });
})();
"""

_INDEX_CSS = """
.layout{grid-template-columns:1fr}
.main{max-width:1150px;margin:0 auto;padding:44px 28px 90px}
th.sortable{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable:hover{text-decoration:underline}
th.sortable::after{content:"\\2195";opacity:.25;margin-left:.4em;font-size:.85em}
th.sorted-asc::after{content:"\\2191";opacity:.8}
th.sorted-desc::after{content:"\\2193";opacity:.8}
.archive-search{margin:0 0 18px}
.archive-search input{font:inherit;font-size:14px;padding:9px 12px;border-radius:8px;width:100%;
  border:1px solid var(--line);background:var(--card);color:var(--ink)}
.search-results{display:flex;flex-direction:column;gap:6px;margin-top:10px;max-height:60vh;overflow:auto}
.search-results .hit{display:block;text-decoration:none;color:var(--ink);padding:8px 12px;border-radius:8px;
  border:1px solid var(--line);background:var(--card)}
.search-results .hit:hover{background:var(--line-soft)}
.search-results .hit-meta{display:block;font-size:11.5px;color:var(--ink-soft);margin-bottom:3px}
.search-results .hit-text{display:block;font-size:13px}
.search-results mark{background:var(--system-bg);color:var(--ink);padding:0 2px;border-radius:3px}
tr[hidden]{display:none}
"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def slugify(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")[:60] or "session"


_KNOWN_EXT = {".html", ".htm", ".txt", ".md", ".tex", ".pdf"}


def out_stem(arg: str) -> Path:
    """--out names the output *stem*: each format adds its own extension.

    'report.pdf' and 'report' both mean report.html / report.txt / ...; an
    unfamiliar suffix ('v2.3') is kept as part of the name."""
    p = Path(arg)
    if p.suffix.lower() in _KNOWN_EXT:
        p = p.with_suffix("")
    return p.with_name(p.name + ".html")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session_id", nargs="?", help="transcript UUID (the .jsonl filename)")
    ap.add_argument("--version", action="version", version=f"transcript_archiver {VERSION}")
    ap.add_argument("--title", default=None, help="page title; defaults to the session's own ai-title")
    ap.add_argument("--out", default=None,
                    help="output path stem for a single archive (each format adds its "
                         "own extension); overrides --archive-dir naming")
    ap.add_argument("--summary-file", default=None,
                    help="HTML fragment (h3/ul blocks) rendered as the session summary")
    ap.add_argument("--projects-root", default=str(Path.home() / ".claude" / "projects"),
                    help="where Claude Code writes sessions (default: ~/.claude/projects)")
    ap.add_argument("--cowork-root", default=str(default_cowork_root()),
                    help="base directory of Claude Desktop cowork (local agent mode) "
                         "sessions, merged into discovery when it exists; pass an "
                         "empty string to disable")
    ap.add_argument("--archive-dir", default=str(DEFAULT_ARCHIVE_DIR),
                    help="where archives and index.html go (default: $CLAUDE_ARCHIVE_DIR "
                         "or ~/claude-archives)")
    ap.add_argument("--no-follow-chain", action="store_true",
                    help="archive exactly the id given, even if a more complete continuation exists")
    ap.add_argument("--max-tool-output", type=int, default=16384,
                    help="elide the middle of tool output longer than this many chars (0 = never)")
    ap.add_argument("--full", action="store_true", help="never elide tool output")
    ap.add_argument("--format", default="html",
                    help="comma-separated: html, text, markdown (md), latex, pdf "
                         "(default: html). pdf compiles the LaTeX with xelatex")
    ap.add_argument("--tool-output", choices=("on", "off"), default="on",
                    help="include tool input and output (default: on). Independent of "
                         "--format. With it off, a tool call is a single labelled line, "
                         "which is usually what you want for latex and pdf: full I/O turns "
                         "a large session into a several-hundred-page document")
    ap.add_argument("--fragment", action="store_true",
                    help="LaTeX body only, no preamble -- ready to \\input into another "
                         "document (requires --format latex)")
    ap.add_argument("--paginate", type=int, default=0, metavar="N",
                    help="split the HTML into pages of N turns (0 = single page). "
                         "Page 1 keeps the summary, usage and fidelity sections; "
                         "the sidebar contents link across pages")
    ap.add_argument("--subagents", choices=("on", "off"), default="on",
                    help="render subagent transcripts (<session>/subagents/agent-*.jsonl) "
                         "as appendix sections (default: on). With off, the files are "
                         "still listed in the fidelity report and their usage still "
                         "counts, but their content is not rendered")
    ap.add_argument("--index", action="store_true",
                    help="rebuild index.html for the archive directory and exit")
    ap.add_argument("--watch", type=int, default=None, metavar="SECONDS",
                    help="with --index: regenerate every SECONDS (min 30) until "
                         "interrupted, and stamp the page to reload itself, so "
                         "the activity column stays fresh")
    ap.add_argument("--import-claude-ai", metavar="CONVERSATIONS_JSON",
                    help="import conversations from a claude.ai data export "
                         "(conversations.json) instead of a local session")
    ap.add_argument("--conversation", default=None,
                    help="with --import-claude-ai: only conversations whose name or "
                         "uuid contains this (case-insensitive)")
    ap.add_argument("--list-conversations", action="store_true",
                    help="with --import-claude-ai: list the export's conversations "
                         "and exit")
    ap.add_argument("--verbose", action="store_true",
                    help="print per-step detail (files parsed, compile passes)")
    ap.add_argument("--quiet", action="store_true",
                    help="print nothing but warnings; the audit log still records everything")
    ap.add_argument("--log-dir", default=None,
                    help="where the per-run audit log goes (default: <archive-dir>/logs)")
    return ap


def _validate(ap: argparse.ArgumentParser, args: argparse.Namespace, formats: tuple) -> None:
    """Reject option combinations that would otherwise be silently ignored."""
    if args.watch is not None and not args.index:
        ap.error("--watch only makes sense with --index")
    if (args.conversation or args.list_conversations) and not args.import_claude_ai:
        ap.error("--conversation and --list-conversations require --import-claude-ai")
    if args.fragment and "pdf" in formats:
        ap.error("--fragment cannot be compiled (it has no preamble); "
                 "use --format latex, or drop --fragment for a PDF")
    if args.fragment and "latex" not in formats:
        ap.error("--fragment applies to --format latex")
    if args.verbose and args.quiet:
        ap.error("--verbose and --quiet are mutually exclusive")


def main(argv: list[str] | None = None) -> None:
    ap = build_parser()
    args = ap.parse_args(argv)
    CON.verbose, CON.quiet = args.verbose, args.quiet

    projects_root = Path(args.projects_root)
    cowork_root = Path(args.cowork_root) if args.cowork_root else None
    archive_dir = Path(args.archive_dir)
    log_dir = Path(args.log_dir) if args.log_dir else archive_dir / "logs"
    run_started = datetime.datetime.now()
    label = args.session_id or ("index" if args.index else "import")

    formats = tuple("markdown" if f.strip().lower() == "md" else f.strip().lower()
                    for f in args.format.split(",") if f.strip())
    unknown = [f for f in formats
               if f not in ("html", "text", "markdown", "latex", "pdf")]
    if unknown:
        ap.error(f"unknown --format value(s): {', '.join(unknown)} "
                 "(choose from html, text, markdown, latex, pdf)")
    _validate(ap, args, formats)

    outcome = "ok"
    try:
        _run(args, ap, projects_root, cowork_root, archive_dir, formats)
    except SystemExit as e:
        if e.code not in (None, 0):
            outcome = f"failed: {e.code}"
            CON.note(str(e.code)) if isinstance(e.code, str) else None
        raise
    except KeyboardInterrupt:
        outcome = "interrupted"
        raise
    except Exception as e:
        outcome = f"crashed: {type(e).__name__}: {e}"
        raise
    finally:
        path = write_audit_log(log_dir, sys.argv, run_started, outcome, label)
        if path:
            CON.detail(f"audit log: {path}")


def _run(args, ap, projects_root: Path, cowork_root, archive_dir: Path, formats: tuple) -> None:
    if args.index:
        if args.watch:
            import time
            period = max(30, args.watch)
            CON.say(f"watching: regenerating the index every {period}s (Ctrl+C to stop)")
            try:
                while True:
                    build_index(archive_dir, projects_root, archive_dir / "index.html",
                                sessions=scan_all_sessions(projects_root, cowork_root),
                                refresh=period)
                    time.sleep(period)
            except KeyboardInterrupt:
                return
        build_index(archive_dir, projects_root, archive_dir / "index.html",
                    sessions=scan_all_sessions(projects_root, cowork_root))
        return

    if args.import_claude_ai:
        convs = load_claude_ai_export(Path(args.import_claude_ai))
        if args.conversation:
            q = args.conversation.lower()
            convs = [c for c in convs
                     if q in (c.get("name") or "").lower()
                     or q in (c.get("uuid") or "").lower()]
        if args.list_conversations or not convs:
            if not convs:
                CON.say("no conversation matches; the export contains:")
            for c in load_claude_ai_export(Path(args.import_claude_ai)):
                CON.say(f"  {(c.get('uuid') or '?')[:8]}  "
                        f"{(c.get('created_at') or '')[:10]}  "
                        f"{len(c.get('chat_messages') or []):4d} msgs  "
                        f"{c.get('name') or '(untitled)'}")
            if not args.list_conversations and not convs:
                sys.exit(1)
            return
        import tempfile
        with tempfile.TemporaryDirectory(prefix="claude-ai-import-") as td:
            troot = Path(td)
            for c in convs:
                sid = c.get("uuid") or "claude-ai-import"
                recs = claude_ai_records(c)
                (troot / f"{sid}.jsonl").write_text(
                    "\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n",
                    encoding="utf-8")
            summary_inner = (Path(args.summary_file).read_text(encoding="utf-8")
                             if args.summary_file else
                             "<p><em>Imported from a claude.ai data export. Pass "
                             "<code>--summary-file</code> for a hand-written "
                             "summary.</em></p>")
            for c in convs:
                sid = c.get("uuid") or "claude-ai-import"
                title = args.title or c.get("name") or sid
                out = (out_stem(args.out) if args.out and len(convs) == 1 else
                       archive_dir / f"{sid[:8]}_{slugify(title)}.html")
                build(sid, title, out, summary_inner, troot,
                      follow_chain=False,
                      max_tool_output=0 if args.full else args.max_tool_output,
                      formats=formats, fragment=args.fragment,
                      tool_output=args.tool_output, subagents=args.subagents,
                      paginate=args.paginate, source_kind="claude.ai")
        return

    if not args.session_id:
        ap.error("a session id is required (or use --index or --import-claude-ai)")

    sessions = scan_all_sessions(projects_root, cowork_root)
    CON.detail(f"{len(sessions)} sessions found under {projects_root}"
               + (f" and {cowork_root}" if cowork_root and cowork_root.is_dir() else ""))
    if args.session_id not in sessions:
        sys.exit(f"No {args.session_id}.jsonl under {projects_root}"
                 + (f" or {cowork_root}" if cowork_root and cowork_root.is_dir() else ""))
    title = args.title or sessions[args.session_id].title or args.session_id

    if args.summary_file:
        summary_inner = Path(args.summary_file).read_text(encoding="utf-8")
    else:
        summary_inner = (
            "<p><em>No summary provided. Write one covering Activities, Key findings, What this "
            "allows going forward, and Generated artifacts, save it as an HTML fragment, and "
            "re-run with <code>--summary-file</code>.</em></p>")

    # Name the file after the transcript actually archived, not the id typed in --
    # otherwise a resumed session gets filed under the id of its own earlier half.
    naming_id = args.session_id
    if not args.no_follow_chain:
        naming_id, _ = resolve_chain(args.session_id, sessions)
    out_path = out_stem(args.out) if args.out else (
        archive_dir / f"{naming_id}_{slugify(title)}.html")

    build(args.session_id, title, out_path, summary_inner, projects_root,
          follow_chain=not args.no_follow_chain,
          max_tool_output=0 if args.full else args.max_tool_output,
          formats=formats, fragment=args.fragment,
          tool_output=args.tool_output, sessions=sessions,
          subagents=args.subagents, paginate=args.paginate)


if __name__ == "__main__":
    main()
