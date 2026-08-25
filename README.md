# claude-session-publisher

Turn a Claude Code session into a single self-contained document — HTML, plain
text, LaTeX or PDF — with a fidelity report proving nothing was silently
dropped.

Claude Code writes every session to a JSON Lines file under
`~/.claude/projects/`. That file is complete but unreadable: interleaved
records, tool payloads, harness bookkeeping. This script parses every record
type into a typed model, decides per class whether to **render**, **fold** or
**count** it, and prints a fidelity report reconciling the three against the
source record count — so the difference between *"not in the transcript"* and
*"not in the source"* is always visible on the page.

Single file, standard library only, no install step.

```bash
python transcript_archiver.py <session-id>
python transcript_archiver.py <session-id> --format html,text,latex,pdf
python transcript_archiver.py --index          # rebuild the index page
```

## Features

- **Five formats from one parse** — HTML, plain text, Markdown, LaTeX and PDF
  all render from the same typed transcript model, so a turn cannot appear in
  one format and vanish from another. `--fragment` emits a LaTeX body ready to
  `\input` into a manuscript, transliterated to compile under pdflatex as well
  as XeLaTeX.
- **Subagent transcripts are part of the record** — a background agent's
  conversation (`<session-id>/subagents/agent-*.jsonl`) is rendered as a
  linked appendix in every format, its usage merged into the cost table, and
  each file listed in the fidelity report. `--subagents off` suppresses the
  content but never the disclosure.
- **Three sources** — Claude Code sessions, Claude Desktop cowork
  (local agent mode) sessions via `--cowork-root`, and claude.ai
  conversations via `--import-claude-ai conversations.json` (from Settings →
  Privacy → Export data), all through the same pipeline and fidelity
  reporting.
- **A fidelity report on every page** — each source record is rendered, folded
  into an earlier turn, or counted as deliberately not rendered, and the three
  numbers are reconciled against the source record count. Corrupt lines are
  counted too. If anything escapes the parser, the page says so instead of
  hiding it.
- **Human turns are verbatim** — typed text and pastes are never run through a
  markdown renderer, so a pasted traceback or columnar benchmark stays
  byte-for-byte intact in every format.
- **Session-chain resolution** — a resumed or bridged conversation is written
  to a new file repeating the earlier records; the archiver finds the most
  complete file by comparing record-uuid sets, follows genuine continuations,
  and refuses to follow forks.
- **Usage and cost accounting** — tokens per model, deduped per `requestId`
  (naively summing the records over-reports output ~2.3× on tool-heavy
  sessions), with cache reads, 5-minute vs 1-hour cache writes, and a
  list-price cost estimate.
- **The harness is visible** — hook output, injected files, skill loads,
  compaction summaries and system records render in a collapsed lane with the
  classification evidence for each, instead of vanishing or masquerading as
  things you typed.
- **Honest about thinking** — Claude Code requests thinking with
  `display: "omitted"`, so the archive shows *that* Claude thought at a given
  point and says plainly that the text never reaches the transcript.
- **Self-contained HTML** — chat-style layout, light and dark themes,
  filterable table of contents, per-lane toggles, keyboard navigation, no
  external assets. `--paginate N` splits a very large session into pages of N
  turns, with the sidebar contents and subagent links pointing across pages.
- **A live index** — `--index` builds a sortable page of every session on
  disk with an activity column whose ages decay in the browser without
  regeneration; `--index --watch 300` keeps regenerating it on a loop and the
  page reloads itself, giving a slow-paced dashboard of which conversations
  are active right now.
- **Tool I/O under your control** — `--tool-output on|off` independent of
  format, and long outputs elided in the middle (`--full` to keep everything),
  with every elision counted on the page.
- **Survives real transcripts** — NUL bytes from UTF-16 console captures,
  ANSI codes, emoji, 65,000-character lines, unresolved tool calls and
  unparseable lines are all handled, counted, and reported.
- Standard library only, one file, 65 tests, CI on Linux/Windows.

## How this compares

[simonw/claude-code-transcripts](https://github.com/simonw/claude-code-transcripts)
is the best-known tool in this space: pip-installable, with an interactive
session picker, paginated mobile-friendly HTML, git-commit timelines, and
one-command publishing to a GitHub Gist. Other exporters
([claude-session-exporter](https://github.com/rubicon/claude-session-exporter)
and several like it) target Markdown for note vaults. This tool's focus is
different: **archival fidelity and print** — the reconciled fidelity report,
verbatim human turns, usage/cost accounting, chain resolution, and
LaTeX/PDF output fit for a paper's appendix. If you want a quick shareable
web link, use Simon's tool; if you want a complete, auditable record or a
document, use this one.

## Roadmap

Remaining gap worth closing: client-side search across a whole archive.
(Subagent rendering, the Markdown format, cowork discovery, the claude.ai
importer, and pagination, formerly listed here, shipped.) Two caveats on the
sources: the cowork directory layout follows Claude Desktop's documented
structure but was tested against synthetic data, and the claude.ai importer
targets the export schema as of mid-2026 — reports with real exports that
parse differently are welcome.

## Scope

The scribe reads the transcript files Claude Code writes to your disk, so what
it can archive is decided by where a session's transcript lives:

| Claude surface | Archivable? |
|---|---|
| Claude Code CLI | **Yes** — its native format. |
| Claude Code desktop app | **Yes** — sessions run locally and write the same files. |
| Claude Code web/mobile, bridged to your machine | **Yes** — the local side writes a transcript, and bridge records are chain-resolved so the pieces come out as one conversation. |
| Claude Desktop cowork (local agent mode) | **Yes** — same format under a different base directory, merged into discovery via `--cowork-root` (auto-detected). |
| claude.ai chats, Claude Desktop chat, mobile app | **Via export** — request your data export (Settings → Privacy → Export data) and run `--import-claude-ai conversations.json`. The export carries no token usage and no model names, and the page says so. |
| Claude Code cloud sessions (never bridged) | No — nothing is written to your disk. |

## Formats

| | |
|---|---|
| `html` | Chat-style page: your turns right, Claude's left, collapsible tool I/O, filterable table of contents, light and dark themes. Self-contained — no external assets. |
| `text` | Plain UTF-8. Human turns and tool output are reproduced byte-for-byte and never re-wrapped. |
| `markdown` | For note vaults (Obsidian etc.). Claude's prose is markdown and passes through live; human turns and tool I/O are fenced verbatim, with fences sized past any backtick run inside them. |
| `latex` | A standalone XeLaTeX document, or with `--fragment` a body you can `\input` into your own paper. |
| `pdf` | The LaTeX compiled with `xelatex` (two passes, for the table of contents). |

All four render from the same parsed transcript, so a turn cannot appear in one
format and vanish from another, and each states in its own header what its
medium cannot carry.

### Tool output

`--tool-output on|off` is independent of `--format`. Tool arguments are
pretty-printed everywhere, but full input and output turns a large session into
a several-hundred-page document, so:

```bash
# a readable PDF: tool calls listed by name, payloads omitted
python transcript_archiver.py <id> --format pdf --tool-output off

# the complete record
python transcript_archiver.py <id> --format html --tool-output on
```

A 1,655-record session is 92 pages with tool output off and 260 with it on.

### Fragments for a paper

`--fragment` emits the body with no preamble, and transliterates every
character so it compiles under **pdflatex** as well as XeLaTeX — Greek becomes
math, arrows and box drawing become ASCII. Your host preamble needs:

```latex
\usepackage{fvextra} \usepackage{xcolor} \usepackage{enumitem}
\usepackage{booktabs} \usepackage[most]{tcolorbox}
```

The turn environments are defined with `\@ifundefined`, so you can restyle
every turn from your own preamble without editing the generated file.

## What it gets right

These were all real defects found by running it over hundreds of thousands of
records, and each is now covered by a test:

- **Usage is deduped per `requestId`.** One API response is written as several
  records that each repeat the same cumulative usage; summing them over-reports
  output tokens by roughly 2.3× on a tool-heavy session.
- **Human vs injected is read from `promptSource`/`origin.kind`**, not guessed
  from the text, so harness-injected prompts are not rendered as things you
  typed.
- **Session chains are resolved.** A resumed or bridged conversation is written
  to a *new* file that repeats the earlier records, so archiving the id you
  happen to name can capture half a conversation. Compare uuid sets, not
  filenames or record counts — the shorter file can hold more conversation.
- **Human turns are never run through the markdown renderer.** They are typed
  text and pastes; interpreting them collapses a pasted traceback into prose.
- **Thinking blocks are always empty.** Claude Code requests them with
  `display: "omitted"`, so an archive can show *that* Claude thought at a given
  point, never what it thought. The page says so rather than implying otherwise.

## Tests

```bash
python tests/test_archiver.py
```

65 checks, run against the synthetic session in `examples/` — self-contained,
no real transcript needed. The LaTeX/PDF compile checks are skipped (not
failed) when no TeX installation is on `PATH`; everything else needs only
Python. To exercise it on a large messy conversation of your own:

```bash
CLAUDE_PROJECTS=~/.claude/projects SAMPLE_SESSION=<id> python tests/test_archiver.py
```

The sample is generated by `examples/make_sample.py` and is deliberately built
to carry the things that broke on real data: a pasted block whose columns must
not be re-wrapped, Greek and box drawing, NUL bytes from UTF-16 output captured
byte-wise, a 3,000-character line, an empty thinking block, an unresolved tool
call, a markdown list that switches marker type mid-stream, a turn quoting the
archiver's own template placeholders, and one deliberately corrupt line the
fidelity report must count rather than silently skip.

## Requirements

Python 3.9+ for the HTML and text formats — standard library only.

LaTeX and PDF need a TeX installation providing `xelatex`, `fvextra`,
`tcolorbox` and the DejaVu fonts (TeX Live's `scheme-full` has all of them).
Fonts are loaded **by filename from TeX Live**, not from the system, so output
does not depend on the machine's font database.

Cost figures come from the `PRICING` table at the top of the script — public
list rates, hardcoded as of August 2026. When rates change, edit that table;
models it does not know are reported as "no list price" rather than priced
wrongly.

## Licence

MIT — see `LICENSE`.
