# Design notes — claude-session-publisher

What this program is trying to be, the decisions that shaped it, what each
one cost, and what was rejected. `README.md` is the product page and
`AGENTS.md` the inventory; this file is the *why*. `CHANGELOG.md` dates
every decision below that arrived after the first release.

## 1. The problem framing

AI-assisted research needs the same standard of record as any other method:
when a result was reached in conversation with a model, the transparency and
reproducibility of the work depend on being able to cite and audit that
conversation, verbatim and complete, in a form a paper can reference.
Claude Code already writes every session to a JSON Lines file, but that file
is unreadable in the way a raw instrument log is unreadable: interleaved
record types, tool payloads, harness bookkeeping, resumed sessions repeated
across files. The tool turns one such file into one self-contained document
and, above all, **proves on the page that nothing was silently dropped**.

Building it taught a second lesson: the records themselves are fragile. In
August 2026 a Claude Desktop reinstall deleted the author's local agent
sessions and the account data export did not include them. So the tool also
serves anyone whose conversations matter, under the motto *archive early,
archive often*.

## 2. Decisions and their trade-offs

| Decision | Why | What it costs / what was rejected |
|---|---|---|
| **Every record is rendered, folded into an earlier turn, or counted, and the three numbers are reconciled against the source record count on the page** (the fidelity report). | The difference between "not in the transcript" and "not in the source" must be visible to a reader, not known only to the author. Corrupt lines are counted too. | A new record type Claude Code starts writing shows up as *counted, not rendered* until the parser learns it. Six such types appeared within 48 hours in August 2026; each was caught by a run over real sessions, never by the synthetic suite. Silently skipping "harness noise" was rejected outright. |
| **Human turns are verbatim in every format.** Typed text and pastes never pass through a markdown renderer. | A pasted traceback or columnar benchmark must survive byte for byte; the user's words are the evidence. | Long pasted lines wrap awkwardly in the page formats; the tool accepts that rather than reflow. |
| **One parsed model, five renderers** (HTML, text, Markdown, LaTeX, PDF as compiled LaTeX). | A turn cannot appear in one format and vanish from another; the fidelity numbers are the same in all five. | Five emitters to keep in step; the suite compares them. |
| **Citable reference tags** (P1…, R1…, subagents A1.P1…), sequential and unique within the document, anchors in the HTML. | A paper needs to say "in prompt P32". | Tags are per document, not per source file; a re-archive after a resumed session may renumber. |
| **Session-chain resolution by record-uuid sets**: follow the most complete continuation, refuse forks. | A resumed or post-`/compact` conversation is written to a new file repeating earlier records; archiving the id given can silently miss the later half. | The heuristic can be overridden (`--no-follow-chain`) and must be, for deliberately archived intermediate ids. |
| **Usage deduped per `requestId`, priced at list price beside Claude Code's own reported cost meter.** | Naively summing records over-reports output tokens about 2.3× on tool-heavy sessions; the meter is the number the user actually saw. | Two cost figures on the page, with a note when the meter is partial. |
| **The harness is visible**: hooks, injected files, skill loads, compaction summaries and system records render in a collapsed lane with their classification evidence. | Hiding them would make the page lie about what shaped the conversation; letting them masquerade as user text would be worse. | Pages get longer; the lane is collapsed by default. |
| **Honest about thinking.** The archive shows *that* Claude thought at a point and says the text never reaches the transcript (`display: omitted`). | A blank block invites the wrong inference in either direction. | Nothing to show; the page says so. |
| **Standard library only, one file, no install.** `xelatex` and `pandoc` are detected and degraded without. | Anyone with Python can archive a session; a tool for keeping records must not itself depend on a moving ecosystem. | The HTML, the JSONL parser, the LaTeX escaper and the PDF page counter in the suite are all hand-written. |
| **`--tool-output off` is the documented choice for LaTeX/PDF**; the HTML keeps everything. | Full tool I/O turns a large session into a several-hundred-page document. | The PDF is then not the complete record; the page says so and points to the HTML. |
| **Markdown tables in LaTeX are cut into chunks of at most 30 rows, each its own `tabular`, and wide tables get wrapping columns** (2.6.4). | A single `tabular` cannot break across a page: a 300-row table compiled to a PDF containing none of its rows while xelatex exited 0. | Repeated headers and "(table continued)" marks; no `longtable` dependency in the preamble. |
| **The suite reads the artefact back** (page counts, extracted text, element counts), not the exit code. | The table loss above passed every source-level check; a renderer downstream of the code can drop content and still succeed. | Slower checks; a TeX installation is optional, and the checks skip, never fail, without one. |
| **`--lang` translates the archiver's own words only** (headings, labels, notes, the index); the conversation is never translated; logs, console and `--help` stay English (2.7.0). | The archive is a record; translating its content would falsify it. The chrome is the tool's, and a Brazilian, Spanish, German or French reader should not need English to read a fidelity report. | Every new chrome string needs four translations in the same commit; the suite scans the source for strays. In a standalone LaTeX document the chrome is wrapped in its language and English stays the document default, so the conversation is hyphenated and spaced by English rules (2.7.1). |
| **A version stamp in every output and an audit log per run** under `<archive-dir>/logs/`, recording the command line, versions, warnings and outcome. | A document that will be cited must say which tool produced it; a run that failed must be diagnosable later. | One more file per run. |
| **Generated archives never enter the repository**: `.gitignore` ignores the output extensions everywhere and whitelists the repository's own documents; the suite asserts it never writes into the user's archive. | A transcript is a verbatim record of a real conversation, including file paths and pasted secrets. | Contributors must whitelist a new tracked `.md`/`.html`/`.pdf` explicitly. |
| **Apache-2.0 with a visible Disclaimer and a non-affiliation note in the README.** | An explicit patent grant, a contributor licence, and the strongest ordinary limitation of liability; nobody reads `LICENSE`. | None worth naming. |

## 3. What was rejected

- **Rendering human turns as markdown.** Prettier, and it would have
  reflowed pasted evidence. Verbatim won.
- **A dependency for the heavy lifting** (a markdown library, `pandoc` as a
  requirement, a PDF library). Each would have made the tool easier to
  write and harder to keep running for years; every one was declined in
  favour of hand-written emitters and optional external programs.
- **Trusting exit codes as validation.** A 64-session pass that recorded
  return codes "validated" a release that lost table rows in the PDF; the
  practice was replaced by reading the produced files back, in the suite and
  in the release ritual.
- **Translating the conversation**, or letting the conversation take the
  chrome language in LaTeX (French polyglossia inserts spaces before `!?:;`
  in English prose). The document language stays English; only the
  archiver's words are wrapped.
- **Summing usage records naively.** Over-reports by ~2.3× on tool-heavy
  sessions; deduplication per request id was adopted instead.
- **Shortening a LaTeX title after escaping it** (2.7.1, reverted in 2.7.2):
  the cut landed inside `\textbackslash{}` on Windows paths and every real
  Windows PDF failed while 417 synthetic checks stayed green. Truncate raw
  text, then escape.

## 4. Who decided what

The direction and every product rule were the author's: the purpose (a
citable, auditable record for research), verbatim human turns, the five
formats, standard library only, the visible fidelity report, the licence
and disclaimer, and the scope of translation (the tool's words, never the
conversation). The implementation, the test suite and the release
engineering were done with Claude in Claude Code under a check-everything
contract, with independent code-review passes after each release; the
README's *How it was built* section gives the effort reconstructed from the
session transcripts and the CRediT contributor table. The lessons in §3
each came from a real failure found by running the tool on the author's own
archive, and each became a rule in the publishing playbook the author's
other repositories follow.

## 5. Threat note

The disclosure policy and the practical summary are in
[`SECURITY.md`](../SECURITY.md); this section is the reasoning behind it.

**The trust boundary is the transcript, not the network.** There is no
network: no HTTP client, no update check, no telemetry, nothing listening.
There are no credentials: no API key, no token, no config file. That removes
most of the surface a tool like this would normally have, and concentrates
what is left in one place — the transcript is untrusted input, and the tool's
whole job is to render it.

It is untrusted because of what a session contains. With `--tool-output on`
(the default) an archive carries the full input and output of every tool call:
files the session read, pages it fetched, command output. None of that is
authored by the user or the model. A hostile string in a fetched page is,
after archiving, a hostile string inside a document you may hand to someone
else.

Three consequences shaped the design:

1. **Escaping is a correctness property, not a formality.** Every piece of
   transcript text reaches HTML through `html.escape` and LaTeX through the
   escaper in the LaTeX writer; verbatim blocks are set as verbatim
   environments rather than escaped inline. The index page embeds the
   cross-archive search corpus as JSON inside `<script type="application/
   json">` with `</` escaped so the block cannot be closed early, and its
   renderer passes every field — text, tag, title, href — through
   `escapeHtml` before it reaches `innerHTML`. A break-out of either escape
   is the most valuable bug report this project can receive.

2. **The typesetter is the one subprocess, and it is powerful.** XeLaTeX can
   read and write files. It is invoked as an argument list with no shell, and
   no argument is built from transcript content — only the `.tex` basename,
   with `cwd` set to that file's directory. The exposure that remains is
   *inside* the document: a string that escapes into a control sequence would
   be executed by the engine. That is why LaTeX escaping is tested against
   real archives rather than trusted, and why a clean exit code is never
   taken as evidence the content survived (v2.6.4: a 300-row table compiled
   to zero rows while xelatex exited 0).

3. **The tool does not redact, and says so.** An archive is faithful by
   design — that is the product — so a credential that appeared in a session
   appears in its archive. No secret-scrubbing filter has ever been built
   into it, and the reasoning for leaving it that way is that a filter
   catching most secrets teaches people to trust it for all of them: a
   faithful archive you are told to read before sharing is safer than a
   filtered one you are invited not to. `--tool-output off` is the blunt
   instrument for the cases where that is not enough. If this is ever
   revisited, it belongs in §3 as a decision with its trade-off, not as a
   quiet feature.

**Writes are bounded and non-destructive.** Output goes under `--archive-dir`,
the `--out` stem, or `--log-dir`, and nothing else is touched. The only files
the tool deletes are the `.aux`/`.out`/`.toc`/`.log` XeLaTeX itself wrote
beside the `.tex`, plus a partial PDF from a compile that failed — never an
earlier good PDF, which is recognised by its file signature taken before the
first pass rather than by a clock. `index.html` is written to a temporary and
renamed into place, so an interrupt or a locked file leaves the previous page
intact rather than a truncated one.

**What is deliberately not defended.** The tool trusts the machine it runs
on. It does not verify that a transcript was really written by Claude Code,
does not sign archives, and does not protect an archive from whoever can read
the directory it was written to. Someone who can write to your
`--projects-root` can put anything they like into an archive you generate —
but they could also just edit the archive.

## 6. Open questions

- **PDF on macOS** and TeX fonts on Linux are unverified by a real run; CI
  runs the suite without TeX on all three platforms.
- **Claude Desktop cowork sessions** were tested against synthetic data
  only; the claude.ai importer against one real export that contained no
  in-project conversations.
- **Scale.** The index rescans every session file on each rebuild; a cached
  scan is the obvious next step for archives of hundreds of sessions.
- **Search** covers prompts across archives; searching responses is not
  built.
- **Claude Code's record types keep changing.** Six new ones appeared during
  one week of August 2026 and were caught by survival runs, not by the suite.
  There is no way to be notified; the mitigation is to keep running real
  sessions through the tool before every tag.

(Translated documentation — README and manual in pt-BR, es, de and fr —
shipped in 2.8.0 with a digest-based staleness check; English remains the
source of truth.)
