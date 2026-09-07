# Platforms

One row per platform the tool was **actually run on**, dated, with what was
run and what it produced. A platform with no row here has not been tried — it
is not a claim of failure, and it is not a claim of support either.

The tool is standard-library Python 3.9+, so the interesting variation is not
the interpreter but the things around it: console encoding, line endings,
filesystem semantics while a file is being rewritten, and whether a TeX engine
is installed at all.

## Rows

| Date | Platform | Python | What was run | Result |
|---|---|---|---|---|
| 2026-09-07 | Windows 10 (10.0.19045), native | 3.13.11 (Anaconda) | full suite with TeX (458) and without (434); `--index` over a 74-archive directory; three real sessions to html,text,markdown,latex,pdf | pass — PDFs of 30, 38 and 464 pages via XeTeX 3.141592653-2.6-0.999998 (TeX Live 2026) |
| 2026-09-07 | ubuntu-latest, windows-latest, macos-latest (GitHub Actions) | 3.9 and 3.13 | pyflakes over the tree, the suite, and `unittest discover`; six jobs, commit `6f91c70` | pass — no TeX on the runners, so the LaTeX/PDF compile checks skip themselves |
| 2026-08-31 | WSL2 Ubuntu (from Windows 10) | 3.14 | a real session to html, text, markdown and latex; `--index` over 88 sessions; `--format pdf` with no `xelatex` installed | pass — every non-PDF format correct; the missing engine fails loudly, as intended |

CI re-runs that matrix on every push, so the second row is the one that goes
stale first; check the Actions tab for the latest commit rather than trusting
the date here.

## Notes per platform

**Windows (native).** The tool's home platform, and the one whose edges cost
the most. Console output is reconfigured to UTF-8 because transcripts are not
cp1252. XeLaTeX writes font names and file paths in whatever encoding the OS
hands it, so the compile subprocess decodes with `encoding="utf-8",
errors="replace"` — without that, a font name buried the real compile result
in a traceback from inside `subprocess`'s reader thread. A file open in a
viewer can be locked against deletion in a way Python's own `open()` does not
reproduce; the suite reproduces it with a `FILE_SHARE_READ`-only Win32 handle.
`index.html` is replaced through a temporary and `os.replace`, so a crash or
a locked file never leaves a half-written landing page.

**Linux.** Run for real in WSL2 (row above) and covered by CI on every push.
The recipe is a plain `python3 transcript_archiver.py …`; nothing about the
tool is Windows-specific. Scanning a project root that lives on `/mnt/c` is
roughly 4× slower than a native path (18 s against 4 s for 281 transcripts) —
that is the Windows filesystem bridge, not the tool.

**macOS.** Covered by CI on every push (suite and pyflakes, three Python
versions of the matrix). No PDF has been produced on a Mac, because there is
no Mac here — see below.

**Docker, mobile.** Out of scope; not pinned for this project.

## What is not verified

Stated plainly, because a platforms file that only lists successes is an
advertisement:

- **PDF on Linux and macOS.** No TeX engine is installed on the GitHub
  runners, and the WSL run above deliberately had none either, so the LaTeX →
  PDF path has only ever been exercised on Windows with TeX Live. The LaTeX
  *source* is generated and checked on every platform; only the typesetting
  step is untested elsewhere. Font availability is the likely difference.
- **Claude Desktop cowork sessions produced on Linux or macOS.** The cowork
  reader is tested against synthetic data only, on every platform.
- **Anything on a Mac beyond CI.** Do not read the macOS CI row as a claim
  that the tool has been used there.

## PDF rendering

`--format pdf` requires `xelatex` on `PATH` and says so and exits if it is
missing — it does not silently fall back to a lesser renderer, because a PDF
that quietly lost its tables is worse than no PDF. Two passes are run so the
table of contents resolves. A failed compile removes the partial PDF it
wrote, keeps any earlier PDF that was already there (recognised by the file's
signature before the first pass, not by a clock), and prints the last 30 lines
of the `.log`.
