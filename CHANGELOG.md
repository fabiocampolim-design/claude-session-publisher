# Changelog

All notable changes to claude-session-publisher. Versions are stamped into
every archive (`archiver v…` in the fidelity report and the index).

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
