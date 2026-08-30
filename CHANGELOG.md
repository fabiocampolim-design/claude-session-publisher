# Changelog

All notable changes to claude-session-publisher. Versions are stamped into
every archive (`archiver v…` in the fidelity report and the index).

## 2.6.4 — 2026-08-29

Findings of a whole-project review. The headline one is a silent loss in the
PDF: the tool's central promise is that nothing is dropped without the page
saying so, and for tables it was not keeping it.

**Fixed**
- **A markdown table in a Claude reply lost rows and cells in LaTeX and PDF.**
  Tables went into a plain `tabular`, which cannot break across a page and
  takes its width from its content. Measured in the compiled PDF: a 100-row
  table kept 63 rows, 200 kept 22, **300 kept none**, and a 12-column table
  lost 35 of its 60 cells off the right edge of the paper. The `.tex` held
  every row throughout and `xelatex` exited 0 with no warning in the log, so
  neither the suite nor the 64-session pass could see it. Tables are now cut
  into chunks of at most 30 typeset rows — consecutive tabulars the breakable
  box can break between, each repeating the header and marked *(table
  continued)* — and a table wider than the line gets equal wrapping
  `p`-columns. HTML, text and Markdown were never affected.
- The box packer costed an already-rendered block by its newline count alone,
  so one enormous unbroken paragraph costed two lines and claimed a whole box
  — the same "TeX capacity exceeded" door 2.6.1 and 2.6.2 closed for pastes
  and fenced blocks, reachable through prose. Such a block is now costed by
  the lines it will actually occupy.

**Added**
- The suite compiles a session whose reply is a 300-row table and counts the
  pages of the resulting PDF: the rows have to arrive, not merely exit 0. A
  standard-library page counter reads the PDF, so the suite keeps its
  no-dependency rule.
- `CITATION.cff`, with suite checks that it exists, names Apache-2.0 and
  tracks `VERSION`; the `SPDX-License-Identifier` header on every source file,
  not only the archiver, with a check per file (githubify rule 17).
- CI runs `pyflakes` over the whole tree before the suite, on all three
  platforms.

**Changed**
- The LaTeX preamble and the `--fragment` package list now include `array`
  (a core LaTeX tools package) for the wrapping table columns.

**Docs**
- The platform badge and the manual's platform limitation say macOS, which CI
  has covered since 2.6; the manual records the v2.6.3 validation pass (64
  sessions, 6,245 pages, 64/64) in place of the older 62-session figure, and
  states the new table behaviour as both a feature and its remaining edge.

## 2.6.3 — 2026-08-29

**Changed**
- Licence: MIT → **Apache License 2.0** (`LICENSE`, `NOTICE`, SPDX header).
  Same freedoms for users; adds an explicit patent grant, a contributor
  licence and a fuller limitation of liability. The README's Licence section
  carries the disclaimer and a non-affiliation note, and the suite guards both.

## 2.6.2 — 2026-08-29

**Fixed**
- A Claude reply or thinking turn that prints a whole file in a fenced
  block went through the markdown renderer into one unbounded box — the
  same "TeX capacity exceeded" as 2.6.1 fixed for pastes, reachable through
  a different door. Markdown turns are now packed by the same rule: the
  fenced block is cut across *(part k/n)* boxes, the prose around it stays
  whole and in order.
- The 2.6.1 box split covered a turn's output only; a tool call's *input*
  (a `Write` carrying a whole file) still went into one breakable box. Input
  and output are now packed together into consecutive boxes, the
  input/output boundary kept as a block boundary, and inline notes
  (`[image omitted]`, `(no result in the source)`) stay in the call's own
  box after its output instead of a separate `(images)` box.
- A trailing newline that pushed a turn just over the limit produced a
  spurious `(part 2/2)` box reading `(empty)`; blank remainders now join the
  previous box.

## 2.6.1 — 2026-08-29

**Fixed**
- A single enormous verbatim turn (a 9,614-line paste) inside one breakable
  LaTeX box exhausted TeX's main memory ("TeX capacity exceeded") — 2 of 62
  real sessions failed the full PDF pass. Turns beyond 1,500 typeset lines
  are now split into consecutive boxes titled *(part k/n)*, the document
  says so, and nothing is omitted. Measured: 4,000 lines in one box
  compiles, 9,614 does not; the split version compiles.

**Validated**
- Full LaTeX/PDF pass over every chain-best real session: 62 sessions,
  5,109 pages, 66 minutes with `--tool-output off`; the two failures above
  were the only ones and are fixed.

## 2.6 — 2026-08-29

**Added**
- **Search across every archive from the index page.** `--index` embeds
  every human prompt of every archive (all pages of a paginated one,
  subagent prompts included) with a deep link to its `#P` anchor; the search
  box on `index.html` lists matching prompts with a highlighted snippet and
  narrows the session table to the sessions that matched. Responses remain
  searchable within a page.
- CI also runs on macOS.

**Fixed**
- `--index` into an archive directory that did not exist yet crashed; it now
  creates the directory, as an export does.
- `docs/build_manual.py` unused import.

**Docs**
- README names the reported cost beside the list estimate, describes
  cross-archive search, and its build story covers the review-driven
  releases; the suite checks those claims stay current.

## 2.5.1 — 2026-08-28

Fixes from the code review of 2.5.

**Fixed**
- The reported cost is now gathered from every file of a resumed session's
  chain: a continuation file repeats the conversation records but not the
  earlier process's `cost-state`, so archiving the continuation dropped run 1
  and wrongly flagged the meter partial (seen on a real two-run session).
- Text, Markdown and LaTeX now carry the reported-cost sentence with its
  coverage; before, they showed the figure only through the subtitle and
  only when coverage was complete.
- A malformed `cost-state` record (non-dict `modelUsage`, non-finite
  `startTime`, non-numeric totals) is skipped instead of aborting the export.
- Chain resolution judges continuation-vs-fork on the *exchanges* (typed
  prompts and assistant records), not on every uuid: a session resumed after
  `/compact` carries the conversation forward but not the old file's
  compaction tail (attachments, boundary, summary — 18 records on a real
  pair), which made the tool call it a fork and archive only half. The
  drop count is still reported; a file missing exchanges is still a fork.
- `AGENTS.md` and the user manual describe the reported cost, its metadata
  keys and the index behaviour; the suite checks they do.
- Index detail expression tidied.

## 2.5 — 2026-08-28

**Added**
- Claude Code's own cost meter. Claude Code ≥ 2.1.9x writes `cost-state`
  records (running cost, per-model cost, lines added/removed). The archiver
  now reports that figure next to the list-price estimate: a *reported cost*
  column in the usage table, a session-info row, `reported_cost_usd`,
  `reported_cost_runs`, `reported_cost_partial`, `lines_added` and
  `lines_removed` in the embedded metadata, and the index shows
  "$X reported" instead of "at list price" when the meter covers the session.
- The meter is per process — every `claude --resume` starts a new counter,
  and runs made before the record existed wrote none — so the figure is the
  sum of the last snapshot of each run, and it is flagged *partial* (page,
  metadata, index falls back to list price) when the session began before
  its first metered run.

## 2.4.1 — 2026-08-28

**Fixed**
- Three record types Claude Code 2.1.9x writes into session files —
  `cost-state` (running cost/usage snapshot), `artifact-comment-monitor` and
  `artifact-autoreact-ledger` (artifact comment bookkeeping) — are classed as
  metadata instead of reported as unhandled. Found while refreshing a
  65-session archive with 2.4.

## 2.4 — 2026-08-28

Consolidation release after a full project review.

**Fixed**
- A Claude paragraph opening with a year (`2024. was …`) rendered as an
  ordered list; numbered items are now at most three digits.
- A fence longer than three backticks reported a stray backtick as its
  language and could be closed by a shorter fence inside it.
- Autolinks in human turns swallowed a trailing escaped apostrophe.
- `--index` flagged any archive whose version did not start with "2" as
  "legacy v1"; the major number is compared now.
- A pasted image's media type from the transcript was interpolated into the
  HTML unescaped.
- A typed prompt sent together with an image (list content with human
  provenance) was rendered as harness-injected text with no P tag.
- Subagent transcripts filed under the *requested* session id were lost when
  chain resolution archived its continuation file.
- `--watch` without `--index`, `--conversation` without
  `--import-claude-ai`, `--fragment` with `pdf` or without `latex` were
  silently ignored (or failed after writing files); they are rejected up front.
- `--out` is now a stem: `--out report.pdf --format html` writes
  `report.html`.
- Worktree bookkeeping records Claude Code 2.1 writes (`worktree-state`,
  `relocated`, `atis-latch`) are classed as metadata instead of reported as
  unhandled — found by the release survival run on a 5,693-record session.

**Added**
- `--version`.
- `--verbose`, `--quiet`, and a per-run audit log under
  `<archive-dir>/logs/` (`--log-dir` to relocate) recording the command line,
  versions, every message and the outcome.
- Theme toggle (light/dark, remembered per browser) and a turn-content search
  box in the HTML page.
- Archives whose source is not a session on disk (claude.ai imports, deleted
  transcripts) are listed by `--index`.
- `CLAUDE_ARCHIVE_DIR` environment variable; the built-in default archive
  directory is now `~/claude-archives`.
- `docs/USER_MANUAL.md` (built to HTML and PDF by `docs/build_manual.py`),
  `AGENTS.md`, this changelog.

**Changed**
- `--help` describes the current tool instead of the v1→v2 changelog.
- Test suite: 192 checks (a tautological check removed; the README's stated
  count is verified by the suite).

## 2.3 — 2026-08-22 … 2026-08-26 (as published)

- Five formats from one parse: HTML, text, Markdown, LaTeX (standalone and
  `--fragment`), PDF.
- Subagent transcripts rendered as a linked appendix; cowork discovery
  (`--cowork-root`); claude.ai export importer (`--import-claude-ai`).
- `--paginate`; index activity column with live decay and `--watch`.
- P/R citation tags in every format; subagent turns prefixed `A<k>.`.
- Seven review bugs fixed with failing-first tests (fork promoted to best,
  template placeholders clobbering content, `</script>` in titles, mixed
  marker lists, unparseable lines invisible, zero-timestamp crash, index
  crash on missing metadata).

## 2.2 — 2026-08-22

- Index gains a `started` column and sortable headers; local timestamps.
- Fidelity caveat no longer claims "written from inside the session" for
  finished sessions.

## 2.1 — 2026-08-20

- Human turns are never markdown-rendered: verbatim, pre-wrap, monospace
  when columnar.

## 2.0 — 2026-08-17

- Extraction layer rewritten: every record type parsed into a typed model,
  render/fold/count disposition with a reconciled fidelity report; usage
  deduped per `requestId`; harness lane; session-chain resolution.
