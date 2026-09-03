# Changelog

All notable changes to claude-session-publisher. Versions are stamped into
every archive (`archiver v…` in the fidelity report and the index).

## 2.7.4 — 2026-09-03

From the independent review of 2.7.3.

**Fixed**
- **A failed compile never turns into a Python traceback.** 2.7.3's cleanup
  unlinked the partial PDF; on Windows a PDF open in a viewer cannot be
  deleted, and that open handle is often the very reason xelatex failed, so
  the diagnostic exit was replaced by a `PermissionError`. Each removal is
  now attempted and reported in the message.
- **A failure before the first page no longer deletes an earlier run's
  PDF.** When xelatex ends with "No pages of output" it never touched the
  file; a PDF older than the run is left in place and the message says so.
- **The `[ERROR]` marker counts against the title width.** 2.7.3 appended it
  after the cut, so an errored title could run 8 characters past the bound
  the cut exists to enforce (more in a translated marker). `shorten()` takes
  the marker as a `suffix` that is never cut and always fits; the LaTeX and
  text emitters use it, so the invariant lives in one place.

## 2.7.3 — 2026-09-03

From the independent review of 2.7.2.

**Fixed**
- **A failed xelatex compile no longer leaves a partial PDF behind.**
  `-halt-on-error` still writes the pages shipped before the error, so a
  failed run left a file that looked like an archive (2.7.1's pass-one PDFs
  had an empty table of contents). The PDF and the aux files are removed;
  the `.tex` and the xelatex `.log` stay for diagnosis and the error message
  says so.
- **The `[ERROR]` marker of a failed tool call survives a long title** in the
  LaTeX and text formats. It was appended before the 72-character cut, so a
  long command line truncated it away and the call read as successful.
  Markdown already kept it outside the cut; HTML was never affected.
- The suite cleans up the temporary directory of the Windows-path check, and
  `CONTRIBUTING.md` no longer suggests `unittest discover`, which imported
  the suite and ran it a second time.

## 2.7.2 — 2026-09-02

From the audit of 2.7.1: the suite and CI were green, the real-data survival
run was not.

**Fixed**
- **`--format pdf` failed on every Windows session with a file-edit snapshot**
  (regression in 2.7.1). The LaTeX title of a system-event box was shortened
  *after* it had been escaped, so the 72-character cut could land inside a
  `\textbackslash{}` and leave a bare `\tex`; xelatex stopped on pass 1 with
  `Undefined control sequence`, the archiver exited 1, and a pass-one PDF with
  an empty table of contents was left behind. The detail is now shortened as
  raw text and escaped afterwards. Three real sessions that failed under 2.7.1
  compile under 2.7.2 (60, 77 and 105 pages, table of contents present).
- The suite renders a Windows-path snapshot title and compiles it under
  xelatex when one is on `PATH` (section 39, three checks); the shipped
  examples use POSIX paths, which is why 417 green checks never saw the cut.

**Added**
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1) and
  `docs/DESIGN.md` (the problem framing, each decision with its trade-off,
  what was rejected, who decided what).
- The vendored publishing checker is now 1.5.1 and pinned to LF in
  `.gitattributes`, so a Windows checkout with `core.autocrlf` keeps it
  byte-identical to the canonical copy.

## 2.7.1 — 2026-08-31

From the independent review of 2.7.0.

**Fixed**
- **A `--fragment` with a non-English `--lang` mangled the archiver's own
  words** — the neutral-mode transliterator stripped their accents
  ("Resume de la session", "Ahnliches"), dropped `ß`/`œ` outright, and
  counted them in the drop-note as transliterated conversation characters
  (a pure-ASCII conversation was told characters had been transliterated).
  Chrome now goes through its own path: accent macros in a fragment, a
  throwaway tally always.
- **The standalone LaTeX made the chrome language the document's default
  language**, so Claude's English prose was hyphenated with French/German/…
  patterns and, for French, got spaces inserted before `!`, `?`, `:`, `;`.
  English stays the default; only the archiver's words are wrapped in
  `\text<lang>{}`; without polyglossia the wrapper is the identity.
- **A `--fragment` did not compile under pdflatex** — in any language, since
  2.4: a subscript transliterated into prose math (`$_{12}$`) got
  `\allowbreak{}` inserted after the `_`, which pdflatex rejects. Found by
  compiling the fragment inside a host document, which the suite now does
  (English and French) whenever pdflatex is on `PATH`.
- Eight parser labels (`Harness nudge`, `Local command output`, `Local
  command caveat`, `Prompt-submit hook`, `Loop heartbeat`, `Skill already
  loaded`, `Interrupted by user`, `Image scaling note`) had no translation
  and were invisible to the suite's completeness check; the check now reads
  the marker tables too.
- The sentences the archiver adds at parse time — the retraction note in a
  safeguard-refusal event, TodoWrite's `{n} item(s)`, ReportFindings'
  `{n} finding(s)` — follow `--lang`.
- One family of reported-cost sentences instead of two: the plain-text note
  is the HTML paragraph flattened, so text/Markdown/LaTeX now also state
  that the meter restarts on resume. Twelve translations fewer to keep in
  sync.

## 2.7.0 — 2026-08-31

**Added**
- **`--lang pt-BR|es|de|fr`** (or `CLAUDE_ARCHIVE_LANG`): the archiver's own
  words — page shell, turn labels, session info, usage and cost notes, the
  fidelity report, the subagent appendix, the index page — in Brazilian
  Portuguese, Spanish, German or French, in every format. The conversation
  itself is never translated: prompts, answers, thinking, tool names, tool
  input and output, system text, model names, titles and paths are the same
  bytes whatever the language, and the audit log, the console and `--help`
  stay English. `<html lang>` and the embedded metadata (`lang`) record the
  choice; the standalone LaTeX sets the matching polyglossia language when
  polyglossia is installed. Parser labels (event badges) are English
  identifiers at parse time and translated where rendered. An unknown value,
  on the flag or in the variable, is refused before anything is written.
- The suite scans the source for every string passed through `_()` and fails
  on any key missing from any language, any translation whose `{fields}`
  differ from its key, and any table entry with no source string; renders the
  fixture in all five languages and checks that no English chrome survives in
  the HTML, text, Markdown or LaTeX while every conversation fragment of the
  English page is present byte for byte; compiles the pt-BR PDF; builds the
  index in pt-BR and confirms its prompt search reads prompts back from
  archives written in any language. The index's prompt regex no longer
  depends on the English turn label.

## 2.6.6 — 2026-08-31

**Fixed**
- **Only the HTML named the archiver version.** The text, Markdown and
  LaTeX exports now carry `archiver v…` in their fidelity report, as the
  HTML and the index always did — a citable archive names its tool in every
  format. Three checks.
- The suite never writes into the user's archive: it snapshots
  `CLAUDE_ARCHIVE_DIR`, points the variable at a throwaway directory before
  the module loads, and its last section asserts both stayed untouched. The
  `--list-conversations` check had been leaving an audit log in the real
  archive on every run (83 of them found). Two checks.

## 2.6.5 — 2026-08-31

Found by regenerating the whole real archive after the first Fable 5 sessions.

**Fixed**
- **A safeguard refusal with model fallback was prose only.** Claude Code
  2.1.25x writes a `system/model_refusal_fallback` record when a message is
  refused: it names the original and fallback models, the refusal category,
  and the uuids of the messages it retracted — which are absent from the
  `.jsonl`. The page showed the notice text under a raw "model refusal
  fallback" badge and nothing else, so a reader could not see that five
  messages of an eight-minute stretch are missing from the source, nor that
  the rest of the session ran on another model. Now: an event *Model fallback
  after a safeguard refusal* with the detail
  `claude-fable-5 -> claude-opus-4-8 (category: cyber), 5 message(s) retracted`
  in every format, the retraction count and their absence stated in the
  body, a *Harness retractions* row in the HTML session info, and a stderr
  note. Ten new checks.
- `system/away_summary` (the recap printed when you return to a session) has
  its own badge, *Away summary*, instead of the raw subtype.
- Text, Markdown and LaTeX now carry an event's detail in its label, as the
  HTML always did.

**Verified**
- First real-world Linux run (WSL2 Ubuntu, Python 3.14): all non-PDF formats
  of a real session, `--index`, and the loud failure without `xelatex`.
- The whole real archive (72 sessions, 88 in the index) regenerated with this
  version: every fidelity report reconciles, no unhandled record types.

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
