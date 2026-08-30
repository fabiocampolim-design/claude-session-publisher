# AGENTS.md — instructions for AI agents using claude-session-publisher

You are operating `transcript_archiver.py` on behalf of a person who wants a
complete, auditable record of a Claude conversation. This file is the
machine-oriented description: what the tool does, the commands, the files it
reads and writes, and the rules you must not break. Humans: hand this file to
your agent ("read AGENTS.md, then archive session X"). The human manual is
`docs/USER_MANUAL.md`; the README is the product page.

## What the tool is

One script, Python 3.9+, standard library only, no install. It parses every
record of a Claude session transcript into a typed model and renders it to
HTML, plain text, Markdown, LaTeX and PDF from that single parse, with a
fidelity report on every page reconciling rendered + folded + counted records
against the source record count.

```
python transcript_archiver.py <session-id> [options]
python transcript_archiver.py --index [--watch SECONDS]
python transcript_archiver.py --import-claude-ai conversations.json [--conversation TEXT | --list-conversations]
python transcript_archiver.py --version | --help
```

## Hard rules

- **Never edit the transcript.** Human turns are reproduced verbatim in every
  format; do not post-process an archive by string replacement (the tool's own
  history has a bug where that clobbered quoted placeholder text).
- **Never commit an archive.** Output files are verbatim records of real
  conversations; `.gitignore` ignores `*.html *.txt *.md *.tex *.pdf` and
  `logs/` for that reason. Only `README.md`, `AGENTS.md`, `CHANGELOG.md`,
  `docs/*` and `tests/baseline_html.txt` are whitelisted.
- **Do not claim what the page does not say.** Thinking blocks are always
  empty (Claude Code uses `display: "omitted"`); the *list cost* is an
  estimate at public rates, and the *reported cost* (Claude Code's own
  meter, from `cost-state` records, Claude Code ≥ 2.1.9x) is per process —
  every resume starts a new counter, so it is summed over runs and flagged
  **partial** when the session began before its first metered run; the
  claude.ai export lacks Project conversations and usage data. Repeat these
  caveats rather than promising more.
- **Re-archiving with a different `--title` creates a second file.** Reuse the
  title (read it from the existing file's `archive-meta` JSON) or delete the
  old file deliberately.
- **Pass `--summary-file` when you have written a summary**; without it the
  page carries a placeholder. Write summaries from a digest of the transcript
  (human turns verbatim, tool census), not by pasting the transcript.
- **Long sessions with full tool I/O produce huge PDFs** (hundreds of pages,
  minutes of xelatex). Use `--tool-output off` for latex/pdf unless the full
  record is wanted.

## Inputs the tool reads

| Path | What |
|---|---|
| `--projects-root` (default `~/.claude/projects`) | `<project>/<session-id>.jsonl` Claude Code sessions; `<project>/<session-id>/subagents/agent-*.jsonl` subagent transcripts |
| `--cowork-root` (auto per platform: `%APPDATA%\Claude\local-agent-mode-sessions`, `~/Library/Application Support/Claude/local-agent-mode-sessions`, `~/.config/Claude/local-agent-mode-sessions`) | Claude Desktop cowork sessions, same schema; `audit.jsonl` skipped; `""` disables |
| `--import-claude-ai FILE` | claude.ai `conversations.json` (Settings → Privacy → Export data); converted to the record model in a temp dir |
| `--summary-file FILE` | HTML fragment for the summary section |
| `CLAUDE_ARCHIVE_DIR` (env) | default for `--archive-dir` |

Record schema facts you can rely on: a resumed/bridged session is written to
a **new** `.jsonl` repeating earlier records — compare `uuid` sets, never
file names or counts (the tool does: `--no-follow-chain` opts out); records
sharing a `requestId` carry identical usage (dedupe, never sum);
`promptSource`/`origin.kind` on user records settle human-vs-injected;
subagent files share no uuids with the parent and are linked through
`toolUseResult.agentId` on the Agent tool's result record.

## Outputs the tool writes

All under `--archive-dir` (default `$CLAUDE_ARCHIVE_DIR` or `~/claude-archives`)
unless `--out STEM` names a single archive's path stem:

| File | Content |
|---|---|
| `<session-id>_<title-slug>.html` (+ `_p2.html`… with `--paginate`) | self-contained page; embedded `<script type="application/json" id="archive-meta">` with title, ids, counts, `list_cost_usd`, `reported_cost_usd` / `reported_cost_runs` / `reported_cost_partial` (null / 0 / null when the session has no `cost-state`), `lines_added` / `lines_removed`, chain, subagents, `source_kind`, `pages` |
| `.txt` | plain text, human turns and tool output byte-for-byte |
| `.md` | Markdown for note vaults; pastes fenced with computed fence length |
| `.tex` / `_fragment.tex` | XeLaTeX standalone / engine-neutral body |
| `.pdf` | xelatex two passes |
| `index.html` | status of every session on disk + archives from imports; embeds `<script type="application/json" id="search-index">` — every human prompt of every archive (`{session_id, title, file, prompts:[{tag, href, text}]}`) powering the page's cross-archive prompt search. The directory is created if missing |
| `logs/<timestamp>_<label>.log` | audit log: versions, exact command, all messages, outcome (`--log-dir` relocates) |

Console: `wrote <file> (<MB>)`, then the turn census, record reconciliation,
subagent count, usage and list cost, and — when the session carries
`cost-state` — `reported=$X (N run(s)[, partial])`. The index shows
"$X reported" only when coverage is complete, else "$Y at list price".
Every format (HTML usage note, text, Markdown, LaTeX) states the reported
figure and its coverage. The meter is gathered from every file of a session
chain, since a continuation file does not repeat the earlier process's
snapshots. `--quiet` silences the console; `--verbose` adds
per-step detail; warnings always go to stderr. Exit code 0 on success; 2 on
invalid arguments; 1 on a failed run (message on stderr).

## Complete option reference

| Option | Default | Notes |
|---|---|---|
| `session_id` | — | required unless `--index` / `--import-claude-ai` |
| `--title` | session `ai-title` | drives the file slug |
| `--out` | — | path **stem**; each format adds its extension |
| `--summary-file` | placeholder | HTML fragment |
| `--projects-root` | `~/.claude/projects` | |
| `--cowork-root` | auto | `""` disables |
| `--archive-dir` | `$CLAUDE_ARCHIVE_DIR` or `~/claude-archives` | |
| `--no-follow-chain` | off | archive exactly the given id |
| `--max-tool-output` | 16384 | chars; middle elided and counted; 0 = never |
| `--full` | off | never elide |
| `--format` | `html` | `html,text,markdown|md,latex,pdf` |
| `--tool-output` | `on` | `off` = one line per tool call; independent of format |
| `--fragment` | off | latex only; rejected with pdf |
| `--paginate` | 0 | turns per HTML page |
| `--subagents` | `on` | `off` keeps the disclosure, drops the content |
| `--index` | — | rebuild index and exit |
| `--watch` | — | seconds (min 30); requires `--index` |
| `--import-claude-ai` | — | conversations.json |
| `--conversation` | — | name/uuid substring filter; requires the import |
| `--list-conversations` | — | list and exit; requires the import |
| `--verbose` / `--quiet` | off | mutually exclusive |
| `--log-dir` | `<archive-dir>/logs` | |
| `--version` / `--help` | | |

## Workflows

**Archive a finished session**

1. `python transcript_archiver.py --index --archive-dir DIR` → open
   `DIR/index.html` or read the console to find the id and see whether a
   continuation exists ("covered").
2. Optionally write `summary.html` (h3/ul fragments: Activities, Key
   findings, What this allows going forward, Generated artifacts).
3. `python transcript_archiver.py <id> --title "…" --summary-file summary.html
   --format html,text,markdown --archive-dir DIR`.
4. For a paper appendix: add `--format latex --fragment --tool-output off`.
5. Re-run `--index`.

**Archive the session you are in**: same commands; the page will report one
unresolved tool call (the archiver's own). Re-run later to refresh.

**Import claude.ai chats**: `--import-claude-ai conversations.json
--list-conversations`, then `--conversation "<name part>" --format html,text`.

**Batch**: drive the script per session in a subprocess so one failure cannot
stop the batch; keep a map of curated titles; finish with `--index`.

**Verify an archive**: the fidelity report's four numbers must reconcile; the
page's own `.human-turn` / `.assistant-turn` census must equal the console
counts; a human turn's `div.raw` computes to `white-space: pre-wrap`.

## Development rules (if you change the tool)

- Failing-first test in `tests/test_archiver.py` for every fix or feature;
  `python tests/test_archiver.py` must end `ALL GREEN`. TeX checks skip
  without TeX; never make them fail.
- HTML and LaTeX render from `md_tokens()`; never add a format-specific
  parser. `tests/baseline_html.txt` guards the HTML byte-for-byte —
  regenerate it only for an intended HTML change.
- CSS/JS ride into templates as `.format` **values**; never post-replace
  placeholders over rendered content.
- Keep `docs/USER_MANUAL.md`, this file and `--help` in sync: the suite fails
  if either document omits a CLI flag or the README's check count drifts.
  Rebuild the manual with `python docs/build_manual.py`.
- **A LaTeX change is not verified until the PDF is read back.** `xelatex`
  exits 0 while silently dropping whatever runs past the page: a `tabular`
  cannot break across pages, so before 2.6.4 a 300-row table compiled to a
  document containing none of its rows, and a wide one lost the cells past
  the right edge. Nothing may go into an unbreakable, unbounded environment —
  tables are chunked (`_tex_table`) and oversized turns are split
  (`_pack_verbatim`). The suite compiles a table-heavy session and counts the
  pages; extend that guard rather than trusting a return code.
- `pyflakes` runs over the whole tree in CI on all three platforms and must
  stay clean: `python -m pyflakes transcript_archiver.py tests docs examples`.
- Every source file carries `SPDX-License-Identifier: Apache-2.0` and the
  copyright line; `CITATION.cff` tracks `VERSION`. The suite checks both.
- Bump `VERSION`, add a `CHANGELOG.md` entry, update `CITATION.cff`, tag the
  release.
