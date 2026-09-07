# Security policy

## Reporting a vulnerability

Report privately through GitHub's **[Report a vulnerability][advisory]** form
on this repository (Security → Advisories). That opens a private advisory
visible only to the maintainer.

Please do not open a public issue for a vulnerability, and do not include a
working exploit in the first message — a description of the class of problem
and the conditions that trigger it is enough to start.

[advisory]: https://github.com/fabiocampolim-design/claude-session-publisher/security/advisories/new

**What to expect.** This is a one-maintainer project, worked on in research
time: an acknowledgement within about a week, and a fix or a clear "won't fix,
here is why" once the report is understood. Only the latest release is
supported; fixes ship in a new release rather than as patches to older tags.

## Scope

In scope: everything in this repository — `transcript_archiver.py`,
`docs/build_manual.py`, the test suite and the CI workflow.

Out of scope: Claude Code itself and the transcript format it writes (report
those to Anthropic), and anything you install to render PDFs (TeX Live,
MiKTeX, pandoc).

## What this tool touches

Useful context for judging impact — the design notes in
[`docs/DESIGN.md`](docs/DESIGN.md) carry the full threat note.

- **Network.** None. The tool never opens a socket: there is no HTTP client
  in it, no update check, no telemetry, and nothing listens on a port. Every
  input is a local file and every output is a local file.
- **Credentials.** None. The tool reads no API key, token or password, and
  has no configuration file. Its only environment variables are
  `CLAUDE_ARCHIVE_DIR` and `CLAUDE_ARCHIVE_LANG`, both documented, both plain
  strings.
- **Processes.** One: `xelatex`, found on `PATH` and invoked for `--format
  pdf` as an argument list — `[exe, "-interaction=nonstopmode",
  "-halt-on-error", <basename>]` with `cwd` set to the `.tex` file's own
  directory. No shell is used anywhere in the tool (`shell=True` appears
  nowhere), and no argument is built from transcript content.
  `docs/build_manual.py`, which builds this repository's own manual, also
  invokes `pandoc`.
- **Files.** Everything is written under `--archive-dir` (or the `--out`
  stem, or `--log-dir`): the archives themselves, `index.html`, and one audit
  log per run. Nothing is written outside those, and nothing is ever deleted
  except the `.aux`/`.out`/`.toc`/`.log` files XeLaTeX itself produced beside
  the `.tex`.

## The interesting attack surface

**Your transcript is the untrusted input.** That is the point worth
understanding before judging a report against this tool.

A Claude Code session records whatever went through it: the text you typed,
the model's replies, and — unless you pass `--tool-output off` — the full
input and output of every tool call. That includes files the session read,
pages it fetched, and command output. So an archive can contain bytes that
came from somewhere neither you nor the model controls, and this tool's job
is to put those bytes into an HTML page, a LaTeX document and a PDF.

Two escapes therefore carry the weight:

- **HTML.** Every piece of transcript text reaches the page through
  `html.escape`. The archive is a single self-contained file with inline
  CSS and JavaScript, opened from disk, so a break-out would be script
  execution in the context of a local file. The index page's cross-archive
  search is the subtlest part of this: it reads prompts back out of the
  archives' own HTML, embeds them as JSON in a `<script type="application/
  json">` block (with `</` escaped so the block cannot be closed early), and
  renders every field — text, tag, title, href — through `escapeHtml` when a
  result is drawn.
- **LaTeX.** Transcript text is escaped for the typesetter, and long or
  columnar blocks are set verbatim. A string that escapes into a control
  sequence would be executed by XeLaTeX, which can read and write files.

A title, a prompt, a tool output or a pasted image that breaks out of either
escape is a vulnerability worth reporting, and is the class of report most
likely to be real.

**Pasted images** are embedded as `data:` URIs from the base64 the transcript
already contains; the tool does not decode, re-encode or otherwise interpret
them.

**Archives are documents, not secrets, and the tool does not redact.** An
archive faithfully reproduces the session, so if a session contained a
credential — pasted, printed by a command, or read out of a file — the
archive contains it too. Read an archive before sharing it. `--tool-output
off` is the blunt instrument that keeps tool input and output out entirely.

## Repository hardening

Dependabot alerts and security updates, secret scanning with push protection,
and private vulnerability reporting are enabled on this repository. The tool
itself has no runtime dependencies — the standard library only — so
[`.github/dependabot.yml`](.github/dependabot.yml) watches the GitHub Actions
that CI pins.
