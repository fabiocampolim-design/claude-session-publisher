"""Checks for transcript_archiver's multi-format export.

Run:  python tests/test_archiver.py
Exits non-zero on the first failing invariant, printing what it expected.
"""
import collections
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE.parent / "transcript_archiver.py"

# By default the suite runs against the synthetic session in examples/, so it
# is self-contained and touches nobody's real transcripts. Point it at your own
# with CLAUDE_PROJECTS=~/.claude/projects and SAMPLE_SESSION=<id> if you want to
# exercise it on a large, messy conversation.
ROOT = pathlib.Path(os.environ.get("CLAUDE_PROJECTS", HERE.parent / "examples"))
SAMPLE = os.environ.get("SAMPLE_SESSION", "00000000-0000-4000-8000-000000000001")

# The suite once used a different session per property, which meant a check
# could pass because its session happened not to contain the thing it tested.
# One sample built to carry all of them is both smaller and harder to fool.
SMALL = BIG = RICH_ID = SAMPLE

spec = importlib.util.spec_from_file_location("ta", SCRIPT)
ta = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ta)

FAILURES = []
CHECKS = [0]


def check(name, cond, detail=""):
    CHECKS[0] += 1
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}   {detail}")
        FAILURES.append(name)


def source_of(sid):
    return [p for p in ROOT.glob("**/*.jsonl")
            if p.stem == sid and "subagents" not in p.parts][0]


def run(sid, fmt, outdir, extra=()):
    cmd = [sys.executable, str(SCRIPT), sid, "--format", fmt,
           "--archive-dir", str(outdir), "--projects-root", str(ROOT), *extra]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=str(SCRIPT.parent))
    return p


def fidelity_numbers(text):
    """(rendered, folded, counted, total) from any format's fidelity report."""
    nums = re.search(
        r"produced one or more turns below\D*?([\d,]+).*?"
        r"folded into an earlier turn[^\d]*?([\d,]+).*?"
        r"counted only[^\d]*?([\d,]+).*?"
        r"total records in the source\D*?([\d,]+)", text, re.S)
    return tuple(int(x.replace(",", "")) for x in nums.groups()) if nums else None


# --------------------------------------------------------------------------
print("\n[1] HTML rendering is unchanged by the tokenizer refactor")
baseline = {}
for line in (HERE / "baseline_html.txt").read_text(encoding="utf-8").splitlines():
    sid8, turns, h = line.split()
    baseline[sid8] = (int(turns.split("=")[1]), h.split("=")[1])
for sid in (SMALL, BIG):
    t = ta.parse_transcript(source_of(sid), 4000)
    body = "".join(str(turn.get("html", "")) for turn in t.turns)
    got = hashlib.sha256(body.encode()).hexdigest()
    want_turns, want_hash = baseline[sid[:8]]
    check(f"{sid[:8]} turn count", len(t.turns) == want_turns,
          f"got {len(t.turns)}, want {want_turns}")
    check(f"{sid[:8]} rendered HTML identical", got == want_hash,
          f"got {got[:16]}, want {want_hash[:16]}")

# --------------------------------------------------------------------------
print("\n[2] Every human turn survives byte-for-byte in the text export")
tmp = pathlib.Path(tempfile.mkdtemp(prefix="ta-test-"))
try:
    p = run(BIG, "text", tmp)
    check("text export exits 0", p.returncode == 0, p.stderr.strip()[-300:])
    txts = list(tmp.glob("*.txt"))
    check("text file written", len(txts) == 1, f"found {[f.name for f in txts]}")
    if txts:
        body = txts[0].read_text(encoding="utf-8", errors="replace")
        t = ta.parse_transcript(source_of(BIG), 4000)
        humans = [turn["text"] for turn in t.turns if turn["kind"] == "human"]
        check("human turns present in source", len(humans) >= 2, f"{len(humans)}")
        missing = [h[:40] for h in humans if h.rstrip() not in body]
        check("all human turns verbatim in text", not missing, f"missing: {missing}")
        check("text carries a fidelity report",
              fidelity_numbers(body) is not None, "no fidelity numbers found")

    # ----------------------------------------------------------------------
    print("\n[3] LaTeX: standalone compiles, --fragment has no preamble")
    p = run(SMALL, "latex", tmp)
    check("latex export exits 0", p.returncode == 0, p.stderr.strip()[-300:])
    texs = [f for f in tmp.glob("*.tex") if "fragment" not in f.name]
    check("tex file written", len(texs) == 1, f"found {[f.name for f in tmp.glob('*.tex')]}")
    if texs:
        src = texs[0].read_text(encoding="utf-8", errors="replace")
        check("standalone has documentclass", "\\documentclass" in src)
        check("standalone has begin/end document",
              "\\begin{document}" in src and "\\end{document}" in src)
        xe = shutil.which("xelatex")
        check("xelatex available", bool(xe), "not on PATH")
        if xe:
            r = subprocess.run([xe, "-interaction=nonstopmode", "-halt-on-error",
                                texs[0].name], cwd=str(tmp),
                               capture_output=True, text=True)
            pdf = texs[0].with_suffix(".pdf")
            check("xelatex compiles the standalone source", r.returncode == 0,
                  (r.stdout or "")[-400:])
            check("compiled pdf is non-empty", pdf.exists() and pdf.stat().st_size > 1000,
                  f"exists={pdf.exists()}")

    p = run(SMALL, "latex", tmp, extra=("--fragment",))
    check("fragment export exits 0", p.returncode == 0, p.stderr.strip()[-300:])
    frags = list(tmp.glob("*fragment*.tex"))
    check("fragment file written", len(frags) == 1, f"found {[f.name for f in frags]}")
    if frags:
        fsrc = frags[0].read_text(encoding="utf-8", errors="replace")
        check("fragment has no documentclass", "\\documentclass" not in fsrc)
        check("fragment has no begin{document}", "\\begin{document}" not in fsrc)
        # A fragment that cannot be \input into a real document is not a
        # fragment. Build a host that only loads the packages its header names.
        host = tmp / "host.tex"
        host.write_text(
            "\\documentclass{article}\n"
            "\\usepackage{fvextra}\\usepackage{xcolor}\\usepackage{enumitem}\n"
            "\\usepackage{booktabs}\\usepackage[most]{tcolorbox}\n"
            "\\begin{document}\n"
            "\\section{Appendix: transcript}\n"
            f"\\input{{{frags[0].stem}}}\n"
            "\\end{document}\n", encoding="utf-8")
        # The fragment exists to drop into someone else's manuscript, and that
        # manuscript picks the engine -- for RevTeX/journal work, pdflatex. It
        # has to compile under both.
        for engine in ("pdflatex", "xelatex"):
            if not shutil.which(engine):
                check(f"{engine} available", False, "not on PATH")
                continue
            for f in tmp.glob("host.*"):
                if f.suffix != ".tex":
                    f.unlink(missing_ok=True)
            r = subprocess.run([engine, "-interaction=nonstopmode", "-halt-on-error",
                                "host.tex"], cwd=str(tmp), capture_output=True,
                               text=True, encoding="utf-8", errors="replace")
            check(f"fragment compiles under {engine} when \\input into a host",
                  r.returncode == 0,
                  next((ln for ln in (r.stdout or "").splitlines()
                        if ln.startswith("!")), "")[:200])
        # And the fragment must not contain characters pdflatex cannot set.
        nonascii = {c for c in fsrc if ord(c) > 0x7F}
        check("fragment is pure ASCII", not nonascii,
              f"{len(nonascii)} non-ASCII: {sorted(nonascii)[:8]}")

    # The session above is tiny and plain, so an ASCII check on it proves very
    # little. Repeat it on one that genuinely carries Greek, subscripts and box
    # drawing -- that is where labels and badges leaked past transliteration.
    # Transcripts discuss LaTeX, so their prose contains things that look like
    # macros and math. Those must be escaped as text, while the math this code
    # generates for Greek must survive. Getting the order wrong let a literal
    # \mathbf{r} quoted in a session reach pdflatex unescaped and halt it.
    print("\n[3b] LaTeX-looking source text is escaped, generated math is not")
    for neutral in (True, False):
        tag = "neutral" if neutral else "xelatex"
        tl = collections.Counter()
        got = ta.tex_inline(r"mathtext requires \mathbf{r} and $x^2$", tl, neutral)
        # \allowbreak{} may sit between the escaped backslash and the word: it
        # is a break opportunity for long paths and prints nothing. What must
        # never happen is \mathbf surviving as a live macro.
        check(f"{tag}: literal backslash escaped",
              "\\textbackslash{}" in got and "\\mathbf{" not in got, got[:110])
        check(f"{tag}: literal dollar escaped", "\\$x" in got, got[:90])
    tl = collections.Counter()
    got = ta.tex_inline("Broadening Γ = 0.08 and 10⁻⁶", tl, neutral=True)
    check("neutral: generated math survives escaping",
          "$\\Gamma$" in got and "$^{-6}$" in got, got[:90])

    RICH = RICH_ID
    try:
        tr = ta.parse_transcript(source_of(RICH), 16384)
        rsrc, rtally = ta.emit_latex(
            tr, {"title": "rich", "session_id": RICH, "subtitle": "",
                 "summary_text": ""}, fragment=True, tool_output=True)
        leaked = {c for c in rsrc if ord(c) > 0x7F}
        check("character-rich session really needed transliteration",
              rtally["transliterated"] > 10, f"only {rtally['transliterated']}")
        check("character-rich fragment is pure ASCII", not leaked,
              f"{len(leaked)} leaked: {sorted(leaked)[:10]}")
    except IndexError:
        check("character-rich session available", False, f"{RICH[:8]} not on disk")

    # ----------------------------------------------------------------------
    print("\n[4] PDF is produced and paginated")
    p = run(SMALL, "pdf", tmp)
    check("pdf export exits 0", p.returncode == 0, p.stderr.strip()[-400:])
    pdfs = list(tmp.glob("*.pdf"))
    check("pdf written", len(pdfs) >= 1, f"found {[f.name for f in pdfs]}")
    if pdfs:
        raw = pdfs[0].read_bytes()
        check("pdf has a valid header", raw[:5] == b"%PDF-", str(raw[:8]))
        # Page objects live inside compressed object streams, so counting the
        # literal bytes reports 0 on a perfectly good PDF. Open it properly.
        try:
            import pymupdf as _fitz
        except ImportError:
            try:
                import fitz as _fitz
            except ImportError:
                _fitz = None
        if _fitz is None:
            check("pdf page count (pymupdf unavailable, skipped)", True)
        else:
            doc = _fitz.open(pdfs[0])
            check("pdf reports at least one page", doc.page_count >= 1,
                  f"page_count={doc.page_count}")
            check("pdf page 1 carries the session id",
                  BIG[:8] in doc[0].get_text() or SMALL[:8] in doc[0].get_text(),
                  "session id missing from first page")
            doc.close()

    # ----------------------------------------------------------------------
    # a5b13e25 carries UTF-16LE tool output captured byte-wise: 1,701 NUL bytes
    # interleaved between letters, plus backspaces. XeLaTeX halts on those with
    # "Text line contains an invalid character"; a browser ignores them.
    print("\n[4b] Control bytes never reach the LaTeX source")
    CTRL = SAMPLE
    try:
        t = ta.parse_transcript(source_of(CTRL), 16384)
        ctx = {"title": "ctrl", "session_id": CTRL, "subtitle": "", "summary_text": ""}
        src, tally = ta.emit_latex(t, ctx, tool_output=True)
        bad = [c for c in src if (ord(c) < 0x20 and c not in "\n\t") or 0x7F <= ord(c) <= 0x9F]
        check("source session really does contain control bytes",
              tally["controls"] > 0, f"tally={tally['controls']}")
        check("no control bytes survive into the .tex", not bad,
              f"{len(bad)} found: {sorted(set(hex(ord(c)) for c in bad))[:5]}")
    except IndexError:
        check("control-byte session available", False, f"{CTRL[:8]} not on disk")

    # ----------------------------------------------------------------------
    print("\n[5] Fidelity numbers agree across every format")
    p = run(BIG, "html,text,latex", tmp)
    check("multi-format export exits 0", p.returncode == 0, p.stderr.strip()[-300:])
    seen = {}
    for ext in ("html", "txt", "tex"):
        files = [f for f in tmp.glob(f"*{BIG[:8]}*.{ext}") if "fragment" not in f.name]
        if not files:
            check(f"{ext} produced for fidelity check", False, "missing")
            continue
        body = files[0].read_text(encoding="utf-8", errors="replace")
        if ext == "html":
            body = re.sub(r"<[^>]+>", " ", body)
        seen[ext] = fidelity_numbers(body)
    check("all formats report fidelity",
          len(seen) == 3 and all(v is not None for v in seen.values()), str(seen))
    if seen and all(v is not None for v in seen.values()):
        check("fidelity identical across formats",
              len(set(seen.values())) == 1, str(seen))
        vals = next(iter(seen.values()))
        check("rendered+folded+counted == total",
              vals[0] + vals[1] + vals[2] == vals[3], str(vals))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{CHECKS[0] - len(FAILURES)}/{CHECKS[0]} checks passed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("ALL GREEN")
