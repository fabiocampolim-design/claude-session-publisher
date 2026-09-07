# Third-party inventory

Everything claude-session-publisher depends on, calls or reproduces, and the
terms each comes under. The tool itself is Apache-2.0 (see [`LICENSE`](../LICENSE)
and [`NOTICE`](../NOTICE)).

The licence column records **what the provider states**, with the link to
where it says it, as checked on 2026-09-07. Terms change; re-read the
source's own page before relying on this table.

## Runtime dependencies

**None.** The Python standard library only, on CPython 3.9 or newer. There is
no `requirements.txt`, no lock file, no `pyproject.toml`, and nothing is
vendored except `tests/conformance.py`, a byte-identical copy of the
maintainer's own publication checker (Apache-2.0, same owner).

The tool is one file. `python transcript_archiver.py --version` on a clean
interpreter is the whole install story.

## Optional external programs

Never bundled, never installed by this tool.

| Program | Used for | Required? | Licence |
|---|---|---|---|
| [XeTeX](https://tug.org/texlive/) (TeX Live, MiKTeX) | `--format pdf` | **Yes, for PDF only** — the tool exits with a message if `xelatex` is not on `PATH` | free licences per package (LPPL, GPL, …) |
| [pandoc](https://pandoc.org) | building *this repository's* manual (`docs/build_manual.py`) | No — a standard-library fallback writes the HTML | GPL-2.0-or-later |

Neither is needed to archive a session in HTML, text, Markdown or LaTeX. The
LaTeX *source* is produced with no TeX installed; only typesetting it needs
an engine.

Development and CI only: [pyflakes](https://github.com/PyCQA/pyflakes) (MIT),
GitHub Actions [`actions/checkout`](https://github.com/actions/checkout) and
[`actions/setup-python`](https://github.com/actions/setup-python) (both MIT).

## Data this tool reads

| Source | What | Terms |
|---|---|---|
| Claude Code session transcripts (`~/.claude/projects/**/*.jsonl`) | the conversations you archive | **yours** — written on your machine by your own use of Claude Code |
| Claude Desktop cowork sessions | same schema, different directory | yours |
| `conversations.json` from claude.ai *Settings → Privacy → Export data* | standalone chats, via `--import-claude-ai` | yours — Anthropic's own export of your account's data |

Everything this tool reads is already on your disk and is your own material.
It fetches nothing, and it sends nothing anywhere: there is no network client
in it (see [`SECURITY.md`](../SECURITY.md)).

## What the archives reproduce

An archive reproduces **your session**, which may quote or embed material
belonging to other people: a paper you pasted, a page a tool fetched, a
snippet of someone's code, an image you dropped in. This tool takes no
position on the licence of that material and does not detect it — it
reproduces what the transcript contains. Before publishing an archive,
satisfy yourself that you may republish what your session pulled in. This is
the same obligation you had when the material entered the session; the
archive only makes it visible.

## Names and trademarks

**Claude** and **Claude Code** are products of, and trademarks of, Anthropic
PBC. This project is an independent tool that reads files Claude Code writes.
It is not affiliated with, endorsed by, or sponsored by Anthropic, and the
names are used only to say what the tool is for — nominative use. The
transcript format is Anthropic's; it is read, never redistributed, and no
Anthropic code is included or derived from.

The product name `claude-session-publisher` was checked against PyPI (no
package of that name) and GitHub at Phase 3 of publication. It is not
registered as a trademark and no claim is made to one.

## AI-usage disclosure

This tool was written with Claude Code, and the division of labour is stated
in [CRediT](https://credit.niso.org/) terms in the README's *"With itself
watching"* section, reconstructed from the project's own archived
transcripts. Nothing in this repository was generated and shipped unread; the
test suite and the survival runs are the evidence, and the CHANGELOG records
which release fixed what and how it was found.
