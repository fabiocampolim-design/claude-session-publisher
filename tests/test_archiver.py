# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
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
import datetime
import re
import shutil
import subprocess
import sys
import tempfile
import zlib

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

# The suite must never write into the user's real archive. Snapshot it before
# anything runs; the last check compares. (Found 2026-08-31: 83 audit logs of
# the --list-conversations check had landed in CLAUDE_ARCHIVE_DIR.)
_REAL_ARCHIVE = (pathlib.Path(os.environ["CLAUDE_ARCHIVE_DIR"])
                 if os.environ.get("CLAUDE_ARCHIVE_DIR") else None)


def _archive_snapshot():
    if not _REAL_ARCHIVE or not _REAL_ARCHIVE.is_dir():
        return None
    return {str(f.relative_to(_REAL_ARCHIVE)) for f in _REAL_ARCHIVE.rglob("*") if f.is_file()}


_ARCHIVE_BEFORE = _archive_snapshot()
# Every check names its --archive-dir; should one forget, the default must be a
# throwaway, never the user's archive. Set before the archiver module is loaded
# (it reads the variable at import) and inherited by every subprocess.
_SUITE_DEFAULT_ARCHIVE = pathlib.Path(tempfile.mkdtemp(prefix="ta-default-archive-"))
os.environ["CLAUDE_ARCHIVE_DIR"] = str(_SUITE_DEFAULT_ARCHIVE)

spec = importlib.util.spec_from_file_location("ta", SCRIPT)
ta = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ta)

FAILURES = []
CHECKS = [0]
SKIPPED = [0]


def check(name, cond, detail=""):
    CHECKS[0] += 1
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}   {detail}")
        FAILURES.append(name)


def skip(name, reason):
    # A missing TeX installation is an environment fact, not a defect in the
    # archiver: report it without failing the suite (html/text need only Python).
    print(f"  SKIP  {name} ({reason})")
    SKIPPED[0] += 1


def pdf_page_count(path):
    """Pages in a PDF, standard library only.

    The suite has no third-party dependency, so the file is read as bytes:
    page objects usually live inside compressed object streams, so every
    FlateDecode stream is inflated and scanned too. Verified against pymupdf
    on nine documents of 2-12 pages.
    """
    raw = pathlib.Path(path).read_bytes()
    n = len(re.findall(rb"/Type\s*/Page[^s]", raw))
    if n:
        return n
    for m in re.finditer(rb"stream\r?\n", raw):
        end = raw.find(b"endstream", m.end())
        if end < 0:
            continue
        try:
            data = zlib.decompress(raw[m.end():end])
        except zlib.error:
            continue
        n += len(re.findall(rb"/Type\s*/Page[^s]", data))
    return n


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
        if not xe:
            skip("standalone compiles under xelatex", "xelatex not on PATH")
            SKIPPED[0] += 1      # and the non-empty-pdf check that follows it
        else:
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
                skip(f"fragment compiles under {engine}", "not on PATH")
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
    if not shutil.which("xelatex"):
        skip("pdf export", "xelatex not on PATH")
        SKIPPED[0] += 4          # the four checks the block would have run
        pdfs = []
    else:
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
    # A real session once carried UTF-16LE tool output captured byte-wise: 1,701 NUL bytes
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

    # ----------------------------------------------------------------------
    # A markdown list that switches marker type mid-stream (- a / 1. b) once
    # rendered only the first run in HTML while LaTeX kept everything -- the
    # exact "appears in one format, vanishes from another" failure the shared
    # tokenizer exists to prevent.
    print("\n[6] Mixed-marker lists survive, whole, in every format")
    md = "- alpha\n- beta\n1. one\n2. two\n- gamma"
    h = ta.md_to_html(md)
    for item in ("alpha", "beta", "one", "two", "gamma"):
        check(f"html keeps '{item}' across marker switches", item in h, h)
    check("html list tags are balanced",
          h.count("<ul>") == h.count("</ul>") and h.count("<ol>") == h.count("</ol>"), h)
    tl = collections.Counter()
    x = ta.md_to_tex(md, tl)
    check("latex keeps every item across marker switches",
          all(i in x for i in ("alpha", "beta", "one", "two", "gamma")), x)
    check("latex gives the ordered run enumerate, the bullet runs itemize",
          "\\begin{enumerate}" in x and "\\begin{itemize}" in x, x)

    # ----------------------------------------------------------------------
    # resolve_chain classifies a diverged session as a "fork" -- and must then
    # never archive that fork in place of the session actually asked for.
    print("\n[7] A fork is reported but never archived in place of the request")

    class _S:
        def __init__(self, uuids):
            self.uuids = uuids
            self.records = len(uuids)
            self.path = None
            self.title = None
            self.first = self.last = None
            self.subagents = 0

    base_u = {f"u{i}" for i in range(100)}
    fork_u = {f"u{i}" for i in range(60)} | {f"f{i}" for i in range(200)}
    best, rel = ta.resolve_chain("base", {"base": _S(base_u), "fork": _S(fork_u)})
    check("diverged session is classified as a fork",
          rel and rel[0]["relation"] == "fork", str(rel))
    check("the fork is not promoted to 'best'", best == "base", f"best={best}")
    cont_u = base_u | {f"s{i}" for i in range(50)}
    best2, _ = ta.resolve_chain("base", {"base": _S(base_u), "cont": _S(cont_u)})
    check("a true superset continuation is still followed", best2 == "cont",
          f"best={best2}")

    # ----------------------------------------------------------------------
    # The sample conversation deliberately contains the literal strings
    # __CSS__, __JS__ and __DROPNOTE__ (a session about this very script
    # would). Template substitution must never touch transcript content.
    print("\n[8] Template placeholders in conversation content are left alone")
    tmp2 = pathlib.Path(tempfile.mkdtemp(prefix="ta-test8-"))
    try:
        p = run(SAMPLE, "html,latex", tmp2)
        check("export exits 0", p.returncode == 0, p.stderr.strip()[-300:])
        pages = list(tmp2.glob("*.html"))
        if pages:
            page = pages[0].read_text(encoding="utf-8", errors="replace")
            check("literal __CSS__ typed by the user survives in the HTML",
                  "__CSS__" in page, "placeholder was substituted inside a turn")
            check("the stylesheet is injected exactly once",
                  page.count("<style>") == 1, f"{page.count('<style>')} style tags")
        texs = [f for f in tmp2.glob("*.tex") if "fragment" not in f.name]
        if texs:
            tex = texs[0].read_text(encoding="utf-8", errors="replace")
            check("literal __DROPNOTE__ typed by the user survives in the LaTeX",
                  "__DROPNOTE__" in tex, "placeholder was substituted inside a turn")

        # ------------------------------------------------------------------
        # The page metadata rides in a <script> block; a title containing
        # </script> must not be able to break out of it.
        print("\n[9] A hostile title cannot break the metadata script block")
        evil = 'x</script><script>alert(1)</script>'
        p = run(SAMPLE, "html", tmp2, extra=("--title", evil, "--out",
                                             str(tmp2 / "evil.html")))
        check("export with hostile title exits 0", p.returncode == 0,
              p.stderr.strip()[-300:])
        ev = (tmp2 / "evil.html")
        if ev.exists():
            page = ev.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'<script type="application/json" id="archive-meta">'
                          r'(.*?)</script>', page, re.S)
            meta = None
            if m:
                try:
                    meta = json.loads(m.group(1))
                except json.JSONDecodeError:
                    meta = None
            check("metadata block still parses as JSON", meta is not None,
                  (m.group(1)[:120] if m else "no meta block found"))
            check("hostile title round-trips intact",
                  bool(meta) and meta.get("title") == evil,
                  repr(meta.get("title")) if meta else "")

        # ------------------------------------------------------------------
        print("\n[10] Degenerate inputs do not crash the report machinery")
        import datetime as _dt
        try:
            ta.fidelity_section(ta.Transcript(), pathlib.Path("none.jsonl"),
                                _dt.datetime.now(_dt.timezone.utc))
            check("fidelity report survives a transcript with no timestamps", True)
        except Exception as e:
            check("fidelity report survives a transcript with no timestamps",
                  False, repr(e))
        # An index entry whose embedded metadata lacks 'records' (hand-edited
        # or future-versioned archive) must not abort the whole index build.
        idx_dir = tmp2 / "arch"
        idx_dir.mkdir()
        (idx_dir / f"{SAMPLE}_x.html").write_text(
            '<script type="application/json" id="archive-meta">'
            f'{{"session_id": "{SAMPLE}", "archiver_version": "2.9", "title": "t"}}'
            '</script>', encoding="utf-8")
        p = subprocess.run([sys.executable, str(SCRIPT), "--index",
                            "--archive-dir", str(idx_dir),
                            "--projects-root", str(ROOT)],
                           capture_output=True, text=True, cwd=str(SCRIPT.parent))
        check("index build survives metadata without a records count",
              p.returncode == 0, p.stderr.strip()[-300:])

        # ------------------------------------------------------------------
        # The sample carries one deliberately corrupt line. "No silent drops"
        # has to include lines the parser could not even read: they must show
        # up in the fidelity report, and the reconciliation must include them.
        print("\n[11] Unparseable lines are visible in the fidelity report")
        raw_lines = [ln for ln in source_of(SAMPLE).read_text(encoding="utf-8")
                     .splitlines() if ln.strip()]
        n_bad = 0
        for ln in raw_lines:
            try:
                json.loads(ln)
            except json.JSONDecodeError:
                n_bad += 1
        check("sample really contains a corrupt line", n_bad >= 1, f"{n_bad}")
        t = ta.parse_transcript(source_of(SAMPLE), 4000)
        check("corrupt line appears among source record types",
              any("unparseable" in str(k) for k in t.record_types),
              str(dict(t.record_types)))
        check("corrupt line appears in counted-only",
              any("unparseable" in str(k) for k in t.counted_only),
              str(dict(t.counted_only)))
        d = t.disposition
        check("reconciliation includes the corrupt line",
              d["rendered"] + d["folded"] + d["counted"]
              == sum(t.record_types.values()) == len(raw_lines),
              f"disp={dict(d)} types={sum(t.record_types.values())} raw={len(raw_lines)}")
        check("attachment record exercises the real schema policy path",
              t.rendered_types.get("harness (hook_success)", 0) == 1,
              str(dict(t.rendered_types)))

        # ------------------------------------------------------------------
        # A background subagent's conversation lives in its own file at
        # <session-id>/subagents/agent-<id>.jsonl. Content fidelity means that
        # text is part of the record: rendered in every format, linked from
        # the tool call that spawned it, and reconciled like everything else.
        print("\n[12] Subagent transcripts are rendered, linked and reconciled")
        AID = "e000000000000001"
        agent_file = ROOT / SAMPLE / "subagents" / f"agent-{AID}.jsonl"
        check("sample provides a subagent transcript", agent_file.exists(),
              str(agent_file))
        tmp4 = pathlib.Path(tempfile.mkdtemp(prefix="ta-test12-"))
        try:
            p = run(SAMPLE, "html,text,latex", tmp4)
            check("export with subagents exits 0", p.returncode == 0,
                  p.stderr.strip()[-300:])
            page = next(iter(tmp4.glob("*.html")), None)
            page = page.read_text(encoding="utf-8", errors="replace") if page else ""
            check("subagent text is rendered in the HTML",
                  "SUBAGENT-MARKER" in page, "marker missing from page")
            check("subagent section carries an anchor",
                  f'id="subagent-{AID}"' in page, "no anchor")
            check("the spawning tool call links to the transcript",
                  f'href="#subagent-{AID}"' in page, "no link from tool call")
            check("fidelity report names the subagent file",
                  f"agent-{AID}" in page, "not in fidelity report")
            m = re.search(r'id="archive-meta">(.*?)</script>', page, re.S)
            meta = json.loads(m.group(1).replace("<\\/", "</")) if m else {}
            # main: 6 requests x 340 output tokens; agent: 1 x 1234
            check("usage totals include the subagent's tokens",
                  meta.get("output_tokens") == 6 * 340 + 1234,
                  f"output_tokens={meta.get('output_tokens')}")
            txt = next(iter(tmp4.glob("*.txt")), None)
            txt = txt.read_text(encoding="utf-8", errors="replace") if txt else ""
            check("subagent text is in the text export",
                  "SUBAGENT-MARKER" in txt, "marker missing")
            check("text export labels the subagent section",
                  f"agent-{AID}" in txt, "no section label")
            tex = next((f for f in tmp4.glob("*.tex")
                        if "fragment" not in f.name), None)
            tex = tex.read_text(encoding="utf-8", errors="replace") if tex else ""
            check("subagent text is in the LaTeX export",
                  "SUBAGENT-MARKER" in tex, "marker missing")

            p = run(SAMPLE, "html", tmp4, extra=("--subagents", "off", "--out",
                                                 str(tmp4 / "noagents.html")))
            check("--subagents off exits 0", p.returncode == 0,
                  p.stderr.strip()[-300:])
            off = (tmp4 / "noagents.html")
            off = off.read_text(encoding="utf-8", errors="replace") if off.exists() else ""
            check("--subagents off omits the transcript",
                  "SUBAGENT-MARKER" not in off, "marker still present")
            check("--subagents off still discloses the file in the fidelity report",
                  f"agent-{AID}" in off, "file not disclosed")
        finally:
            shutil.rmtree(tmp4, ignore_errors=True)

        # ------------------------------------------------------------------
        # Claude Desktop's cowork (local agent mode) writes the same session
        # format under a different base directory:
        #   <base>/<space>/<org>/local_<id>/.claude/projects/<proj>/<sid>.jsonl
        # --cowork-root merges those sessions into discovery; audit.jsonl is
        # bookkeeping, not a session, and must not be listed as one.
        print("\n[13] Cowork sessions are discovered via --cowork-root")
        tmp5 = pathlib.Path(tempfile.mkdtemp(prefix="ta-test13-"))
        try:
            CW_SID = "11111111-2222-4333-8444-555555555555"
            proj = (tmp5 / "cw" / "My Space" / "org-1" / "local_ab12"
                    / ".claude" / "projects" / "some-project")
            proj.mkdir(parents=True)
            recs = [
                {"type": "ai-title", "aiTitle": "Cowork test session",
                 "sessionId": CW_SID},
                {"type": "user", "sessionId": CW_SID, "uuid": "cw-u1",
                 "timestamp": "2026-02-01T10:00:00Z", "promptSource": "typed",
                 "origin": {"kind": "human"},
                 "message": {"role": "user",
                             "content": "COWORK-MARKER: summarize the notes"}},
                {"type": "assistant", "sessionId": CW_SID, "uuid": "cw-a1",
                 "timestamp": "2026-02-01T10:00:10Z", "requestId": "cw_r1",
                 "message": {"role": "assistant", "model": "claude-opus-5",
                             "content": [{"type": "text",
                                          "text": "Here is the summary."}],
                             "usage": {"input_tokens": 10, "output_tokens": 20}}},
            ]
            (proj / f"{CW_SID}.jsonl").write_text(
                "\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
            (proj / "audit.jsonl").write_text(
                '{"type": "audit", "event": "not a session"}\n', encoding="utf-8")
            out5 = tmp5 / "out"
            p = subprocess.run(
                [sys.executable, str(SCRIPT), CW_SID, "--format", "html",
                 "--archive-dir", str(out5), "--projects-root", str(ROOT),
                 "--cowork-root", str(tmp5 / "cw")],
                capture_output=True, text=True, cwd=str(SCRIPT.parent))
            check("cowork session archives via --cowork-root", p.returncode == 0,
                  p.stderr.strip()[-300:])
            pages = list(out5.glob("*.html")) if out5.exists() else []
            body = pages[0].read_text(encoding="utf-8", errors="replace") if pages else ""
            check("cowork content is rendered", "COWORK-MARKER" in body,
                  "marker missing")
            p = subprocess.run(
                [sys.executable, str(SCRIPT), "--index",
                 "--archive-dir", str(out5), "--projects-root", str(ROOT),
                 "--cowork-root", str(tmp5 / "cw")],
                capture_output=True, text=True, cwd=str(SCRIPT.parent))
            check("index build merges cowork sessions", p.returncode == 0,
                  p.stderr.strip()[-300:])
            idx = (out5 / "index.html").read_text(encoding="utf-8",
                                                  errors="replace") \
                if (out5 / "index.html").exists() else ""
            check("index lists the cowork session", CW_SID[:8] in idx, "missing")
            check("audit.jsonl is not listed as a session", "audit" not in idx,
                  "audit leaked into the index")
        finally:
            shutil.rmtree(tmp5, ignore_errors=True)

        # ------------------------------------------------------------------
        # claude.ai's data export ships a conversations.json in a different
        # schema. --import-claude-ai converts each conversation into the
        # record model and drives the normal pipeline, so every format and
        # the fidelity report work unchanged.
        print("\n[14] claude.ai exports import through the same pipeline")
        CAI = HERE.parent / "examples" / "claude-ai-export-sample.json"
        check("claude.ai sample export exists", CAI.exists(), str(CAI))
        tmp6 = pathlib.Path(tempfile.mkdtemp(prefix="ta-test14-"))
        try:
            p = subprocess.run(
                [sys.executable, str(SCRIPT), "--import-claude-ai", str(CAI),
                 "--list-conversations", "--archive-dir", str(tmp6)],
                capture_output=True, text=True, cwd=str(SCRIPT.parent))
            check("--list-conversations exits 0", p.returncode == 0,
                  p.stderr.strip()[-300:])
            check("listing names both conversations",
                  "Band structure question" in p.stdout
                  and "Grocery list" in p.stdout, p.stdout[-300:])
            p = subprocess.run(
                [sys.executable, str(SCRIPT), "--import-claude-ai", str(CAI),
                 "--conversation", "band", "--format", "html,text",
                 "--archive-dir", str(tmp6)],
                capture_output=True, text=True, cwd=str(SCRIPT.parent))
            check("import of one conversation exits 0", p.returncode == 0,
                  p.stderr.strip()[-300:])
            pages = list(tmp6.glob("*.html"))
            check("exactly the filtered conversation is archived",
                  len(pages) == 1, str([f.name for f in pages]))
            body = pages[0].read_text(encoding="utf-8", errors="replace") if pages else ""
            check("imported human text is rendered", "CLAUDE-AI-MARKER" in body,
                  "marker missing")
            check("human turn stays verbatim (not markdown-rendered)",
                  "E(eV)" in body and "<hr>" not in body.split("CLAUDE-AI-MARKER")[-1][:400],
                  "pasted columns were reinterpreted")
            check("assistant markdown is rendered",
                  "<strong>equivalent</strong>" in body, "markdown not rendered")
            check("attachment content travels", "lattice constant a = 2.46" in body,
                  "attachment extracted_content missing")
            check("provenance is stated on the page",
                  "claude.ai" in body, "no provenance note")
            check("fidelity report present in an import",
                  fidelity_numbers(re.sub(r"<[^>]+>", " ", body)) is not None,
                  "no fidelity numbers")
            txt = next(iter(tmp6.glob("*.txt")), None)
            txt = txt.read_text(encoding="utf-8", errors="replace") if txt else ""
            check("text format works for imports", "CLAUDE-AI-MARKER" in txt,
                  "marker missing from .txt")
        finally:
            shutil.rmtree(tmp6, ignore_errors=True)

        # ------------------------------------------------------------------
        # Markdown output: Claude's prose IS markdown and passes through
        # untouched; human turns and tool I/O are fenced so nothing in them
        # can be reinterpreted, with fences long enough to contain any
        # backtick run in the content.
        print("\n[15] Markdown export keeps prose live and pastes fenced")
        tmp7 = pathlib.Path(tempfile.mkdtemp(prefix="ta-test15-"))
        try:
            p = run(SAMPLE, "markdown", tmp7)
            check("markdown export exits 0", p.returncode == 0,
                  p.stderr.strip()[-300:])
            mds = list(tmp7.glob("*.md"))
            check("markdown file written", len(mds) == 1,
                  str([f.name for f in mds]))
            md = mds[0].read_text(encoding="utf-8", errors="replace") if mds else ""
            t = ta.parse_transcript(source_of(SAMPLE), 4000)
            humans = [x["text"] for x in t.turns if x["kind"] == "human"]
            missing = [h[:40] for h in humans if h.rstrip() not in md]
            check("every human turn is present verbatim", not missing,
                  f"missing: {missing}")
            # the sample's assistant table must arrive as live markdown
            check("assistant markdown passes through",
                  "| lattice constant | 3.61" in md, "table not live")
            # the code fence inside assistant prose must survive fencing logic
            check("fidelity numbers present and consistent",
                  fidelity_numbers(md) is not None, "no fidelity numbers")
            check("subagent transcript included in markdown",
                  "SUBAGENT-MARKER" in md, "marker missing")
            check("tool call present", "check numpy version" in md
                  or "python -c" in md, "tool input missing")
        finally:
            shutil.rmtree(tmp7, ignore_errors=True)

        # ------------------------------------------------------------------
        # The index gets an activity column: a session whose last record is
        # recent shows as active, an old one does not, and the cell carries
        # the raw timestamp so the page's own JS can let the state decay
        # without regenerating. --index --watch N regenerates on a loop and
        # stamps the page to reload itself.
        print("\n[16] Index activity column, live decay, and watch mode")
        tmp8 = pathlib.Path(tempfile.mkdtemp(prefix="ta-test16-"))
        try:
            import datetime as _dt
            root8 = tmp8 / "projects" / "proj"
            root8.mkdir(parents=True)
            NOW_SID = "22222222-3333-4444-8555-666666666666"
            now_iso = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            recs = [{"type": "user", "sessionId": NOW_SID, "uuid": "n-1",
                     "timestamp": now_iso, "promptSource": "typed",
                     "origin": {"kind": "human"},
                     "message": {"role": "user", "content": "still working"}}]
            (root8 / f"{NOW_SID}.jsonl").write_text(
                "\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
            # copy the (old-dated) sample beside it
            shutil.copy(source_of(SAMPLE), root8 / f"{SAMPLE}.jsonl")
            out8 = tmp8 / "arch"
            out8.mkdir()
            ta.build_index(out8, tmp8 / "projects", out8 / "index.html")
            idx = (out8 / "index.html").read_text(encoding="utf-8",
                                                  errors="replace")
            def row_of(sid):
                i = idx.find(sid[:8])
                return idx[max(0, i - 400):i + 400]
            check("recent session shows as active",
                  'pill act' in row_of(NOW_SID), row_of(NOW_SID)[:200])
            check("old session does not show as active",
                  'pill act' not in row_of(SAMPLE), row_of(SAMPLE)[:200])
            check("activity cells carry the raw timestamp for live decay",
                  'data-ts="' in idx, "no data-ts attributes")
            check("index JS updates activity ages client-side",
                  "data-ts" in idx.split("<script>")[-1], "no updater in JS")
            check("no auto-reload without --watch",
                  "http-equiv" not in idx, "unexpected meta refresh")
            ta.build_index(out8, tmp8 / "projects", out8 / "index.html",
                           refresh=120)
            idx2 = (out8 / "index.html").read_text(encoding="utf-8",
                                                   errors="replace")
            check("watch mode stamps the page to reload itself",
                  'http-equiv="refresh" content="120"' in idx2, "no meta refresh")
        finally:
            shutil.rmtree(tmp8, ignore_errors=True)

        # ------------------------------------------------------------------
        # Pagination: --paginate N splits the HTML into pages of N turns.
        # Page 1 keeps the summary/usage/fidelity sections; every turn
        # appears on exactly one page; the TOC and the subagent links say
        # which page their target is on.
        print("\n[17] --paginate splits the HTML without losing or doubling turns")
        tmp9 = pathlib.Path(tempfile.mkdtemp(prefix="ta-test17-"))
        try:
            p = run(SAMPLE, "html", tmp9, extra=("--paginate", "4"))
            check("paginated export exits 0", p.returncode == 0,
                  p.stderr.strip()[-300:])
            pages9 = sorted(tmp9.glob("*.html"))
            check("more than one page written", len(pages9) >= 2,
                  str([f.name for f in pages9]))
            bodies = {f.name: f.read_text(encoding="utf-8", errors="replace")
                      for f in pages9}
            all_html = "".join(bodies.values())
            t9 = ta.parse_transcript(source_of(SAMPLE), 16384)
            n_units = len(t9.turns)
            # strip the per-page <script> blocks: the page JS contains the
            # literal string data-lane= in a selector
            markup_only = re.sub(r"(?s)<script.*?</script>", "", all_html)
            got_units = markup_only.count('data-lane=')
            # main turns + one subagent block (which nests its own turns)
            at9 = ta.parse_transcript(
                ROOT / SAMPLE / "subagents" / "agent-e000000000000001.jsonl", 16384)
            want_units = n_units + 1 + len(at9.turns)
            check("every turn appears exactly once across pages",
                  got_units == want_units,
                  f"got {got_units}, want {want_units}")
            first = bodies[sorted(bodies)[0]]
            check("page 1 keeps the fidelity report",
                  "Fidelity report" in first, "fidelity not on page 1")
            later = "".join(v for k, v in bodies.items()
                            if k != sorted(bodies)[0])
            check("later pages do not repeat the fidelity report",
                  "Record disposition" not in later, "fidelity repeated")
            check("pages link each other",
                  "page-nav" in first and "page-nav" in later, "no nav")
            # every internal href resolves somewhere in the union of pages
            hrefs = set(re.findall(r'href="#([^"]+)"', all_html))
            ids = set(re.findall(r'id="([^"]+)"', all_html))
            dangling = hrefs - ids
            check("no dangling same-page anchors", not dangling,
                  str(sorted(dangling))[:200])
            cross = re.findall(r'href="([^"#]+\.html)#([^"]+)"', all_html)
            bad = [f"{f}#{a}" for f, a in cross
                   if f not in bodies or f'id="{a}"' not in bodies[f]]
            check("no dangling cross-page anchors", not bad, str(bad)[:200])
            check("subagent link names the page that holds the transcript",
                  any(a.startswith("subagent-") for _f, a in cross)
                  or 'href="#subagent-' in all_html, "subagent link missing")
        finally:
            shutil.rmtree(tmp9, ignore_errors=True)

        # ------------------------------------------------------------------
        # Structural validation of the single-page HTML: the page's own turn
        # census must equal the parser's counts, tags must balance, and
        # every same-page anchor must resolve.
        print("\n[18] Single-page HTML validates structurally")
        tmp10 = pathlib.Path(tempfile.mkdtemp(prefix="ta-test18-"))
        try:
            p = run(SAMPLE, "html", tmp10)
            check("export exits 0", p.returncode == 0, p.stderr.strip()[-300:])
            page = next(iter(tmp10.glob("*.html"))).read_text(
                encoding="utf-8", errors="replace")
            t10 = ta.parse_transcript(source_of(SAMPLE), 16384)
            census = {
                "human-turn": page.count('class="turn human-turn"'),
                "assistant-turn": page.count('class="turn assistant-turn"'),
            }
            at10 = ta.parse_transcript(
                ROOT / SAMPLE / "subagents" / "agent-e000000000000001.jsonl",
                16384)
            check("page census matches parser: human turns",
                  census["human-turn"]
                  == t10.rendered_types.get("human turn", 0)
                  + t10.rendered_types.get("pasted image", 0)
                  + at10.rendered_types.get("human turn", 0),
                  f"page={census['human-turn']} "
                  f"parsed main={t10.rendered_types.get('human turn', 0)} "
                  f"agent={at10.rendered_types.get('human turn', 0)}")
            check("page census matches parser: assistant turns",
                  census["assistant-turn"]
                  == t10.rendered_types.get("assistant text", 0)
                  + ta.parse_transcript(
                      ROOT / SAMPLE / "subagents"
                      / "agent-e000000000000001.jsonl", 16384
                    ).rendered_types.get("assistant text", 0),
                  str(census))
            check("section tags balance",
                  page.count("<section") == page.count("</section>"),
                  f"{page.count('<section')} vs {page.count('</section>')}")
            check("details tags balance",
                  page.count("<details") == page.count("</details>"),
                  f"{page.count('<details')} vs {page.count('</details>')}")
            hrefs = {h for h in re.findall(r'href="#([^"]+)"', page)}
            ids = set(re.findall(r'id="([^"]+)"', page))
            check("every same-page anchor resolves", not (hrefs - ids),
                  str(sorted(hrefs - ids))[:200])
        finally:
            shutil.rmtree(tmp10, ignore_errors=True)

        # ------------------------------------------------------------------
        # Reference tags: every human prompt is Pn, every Claude response Rn,
        # sequential within the conversation, so main text can cite "in
        # prompt P32" / "in response R12". Subagent turns get an A<k>. prefix
        # so tags stay unique across the whole document. The tag sits by the
        # speaker label; the timestamp stays on the other side of the box.
        print("\n[19] P/R reference tags are sequential, unique, in every format")
        tmp11 = pathlib.Path(tempfile.mkdtemp(prefix="ta-test19-"))
        try:
            p = run(SAMPLE, "html,text,markdown,latex", tmp11)
            check("tagged export exits 0", p.returncode == 0,
                  p.stderr.strip()[-300:])
            page = next(iter(tmp11.glob("*.html")), None)
            page = page.read_text(encoding="utf-8", errors="replace") if page else ""
            for tag in ("P1", "P2", "P3", "R1"):
                check(f"html carries tag {tag} as an anchor",
                      f'id="{tag}"' in page, "missing")
            check("html has no phantom P4", 'id="P4"' not in page, "P4 present")
            check("tags are unique", page.count('id="P1"') == 1,
                  f"{page.count(chr(34) + 'P1' + chr(34))}")
            check("subagent turns carry the A-prefixed tag",
                  'id="A1.P1"' in page and 'id="A1.R1"' in page, "missing")
            txt = next(iter(tmp11.glob("*.txt")), None)
            txt = txt.read_text(encoding="utf-8", errors="replace") if txt else ""
            check("text format tags prompts", "HUMAN - P1" in txt, "no HUMAN - P1")
            check("text format tags responses", "CLAUDE - R1" in txt, "no CLAUDE - R1")
            md = next(iter(tmp11.glob("*.md")), None)
            md = md.read_text(encoding="utf-8", errors="replace") if md else ""
            check("markdown tags prompts", "## Human - P1 " in md,
                  "no tagged heading")
            check("markdown tags responses", "## Claude - R1 " in md,
                  "no tagged heading")
            tex = next((f for f in tmp11.glob("*.tex")
                        if "fragment" not in f.name), None)
            tex = tex.read_text(encoding="utf-8", errors="replace") if tex else ""
            check("latex tags sit by the label, timestamp flushed right",
                  "HUMAN - P1 \\hfill" in tex and "CLAUDE - R1 \\hfill" in tex,
                  "tags not in box titles")
            check("latex titles span the full width so \\hfill can separate",
                  "attach boxed title" not in tex,
                  "content-hugging title tab defeats \\hfill")
            check("latex timestamps are styled smaller than the label",
                  "\\hfill {\\normalfont\\scriptsize\\ttfamily" in tex,
                  "timestamp not de-emphasized")
            check("latex subagent tags carry the prefix", "A1.P1" in tex,
                  "missing")
        finally:
            shutil.rmtree(tmp11, ignore_errors=True)

        # ------------------------------------------------------------------
        # The committed showcase conversation must archive cleanly, and a
        # pasted image must be announced as such in the page-based formats,
        # not surface as an empty mystery box.
        print("\n[20] Showcase conversation archives cleanly in every format")
        SHOW = "0000c0de-cafe-4000-8000-00000000f00d"
        tmp12 = pathlib.Path(tempfile.mkdtemp(prefix="ta-test20-"))
        try:
            check("showcase fixture exists",
                  (ROOT / f"{SHOW}.jsonl").exists(), "run examples/make_showcase.py")
            p = run(SHOW, "html,text,markdown,latex", tmp12)
            check("showcase export exits 0", p.returncode == 0,
                  p.stderr.strip()[-300:])
            tex = next((f for f in tmp12.glob("*.tex")
                        if "fragment" not in f.name), None)
            tex = tex.read_text(encoding="utf-8", errors="replace") if tex else ""
            check("pasted image announced in latex",
                  "PASTED IMAGE" in tex and "user\\_image" not in tex,
                  "image rendered as generic raw block")
            txt = next(iter(tmp12.glob("*.txt")), None)
            txt = txt.read_text(encoding="utf-8", errors="replace") if txt else ""
            check("pasted image announced in text", "PASTED IMAGE" in txt,
                  "missing")
            page = next(iter(tmp12.glob("*.html")), None)
            page = page.read_text(encoding="utf-8", errors="replace") if page else ""
            check("pasted image embedded in html", "data:image/png;base64" in page,
                  "image not embedded")
        finally:
            shutil.rmtree(tmp12, ignore_errors=True)

        # ------------------------------------------------------------------
        # 2026-08-28 review: every finding below got a failing check first.
        print("\n[21] Markdown edge cases: numeric prose, long fences, autolinks")
        h = ta.md_to_html("2024. was a good year\nnext line")
        check("a paragraph opening with a year is not an ordered list",
              "<ol>" not in h and "2024. was a good year" in h, h)
        h = ta.md_to_html("1. one\n2. two")
        check("a real numbered list still renders as <ol>", "<ol>" in h, h)
        h = ta.md_to_html("````\ncode with ``` inside\n````\nafter")
        check("a four-backtick fence carries no phantom language",
              "data-lang" not in h and "```" in h and "<p>after</p>" in h, h)
        h = ta.md_to_html("````python\nx = 1\n````")
        check("a four-backtick fence keeps its real language",
              'data-lang="python"' in h, h)
        hh = ta.human_html("see http://x.com/a&b's page")
        check("autolink stops before an apostrophe (escaping after linking)",
              'href="http://x.com/a&amp;b"' in hh and "&#x27;s page" in hh, hh)

        # ------------------------------------------------------------------
        print("\n[22] Pasted-image media type is escaped in the HTML")
        t21 = ta.Transcript()
        t21.turns = [{"kind": "user_image", "ts": None,
                      "media": 'image/png" onerror="x', "data": "AAAA"}]
        units21, _ = ta.render_turns(t21)
        check("hostile media_type cannot break out of the src attribute",
              '" onerror="' not in units21[0][0] and "&quot;" in units21[0][0],
              units21[0][0][:200])

        # ------------------------------------------------------------------
        print("\n[23] Index version check and imported archives")
        tmp13 = pathlib.Path(tempfile.mkdtemp(prefix="ta-test23-"))
        try:
            arch = tmp13 / "arch"
            arch.mkdir()
            (arch / f"{SAMPLE}_x.html").write_text(
                '<script type="application/json" id="archive-meta">'
                f'{{"session_id": "{SAMPLE}", "archiver_version": "3.0", '
                '"title": "future", "records": 1}</script>', encoding="utf-8")
            (arch / "abcd1234_imported.html").write_text(
                '<script type="application/json" id="archive-meta">'
                '{"session_id": "abcd1234-0000-4000-8000-000000000000", '
                f'"archiver_version": "{ta.VERSION}", "title": "IMPORTED-TITLE", '
                '"records": 5, "source_kind": "claude.ai", '
                '"started": "2026-01-01T00:00:00+00:00", '
                '"last_record": "2026-01-01T01:00:00+00:00"}</script>',
                encoding="utf-8")
            ta.build_index(arch, ROOT, arch / "index.html")
            idx = (arch / "index.html").read_text(encoding="utf-8", errors="replace")
            check("a 3.x archive is not flagged as legacy v1",
                  "legacy v1" not in idx, "legacy pill present")
            check("an imported claude.ai archive is listed in the index",
                  "IMPORTED-TITLE" in idx, "import missing from index")
        finally:
            shutil.rmtree(tmp13, ignore_errors=True)

        # ------------------------------------------------------------------
        print("\n[24] CLI validation, --out stem, --version, --help")
        tmp14 = pathlib.Path(tempfile.mkdtemp(prefix="ta-test24-"))
        try:
            p = subprocess.run([sys.executable, str(SCRIPT), SAMPLE, "--watch", "30",
                                "--projects-root", str(ROOT), "--archive-dir", str(tmp14)],
                               capture_output=True, text=True, cwd=str(SCRIPT.parent))
            check("--watch without --index is rejected",
                  p.returncode != 0 and "--index" in p.stderr, p.stderr[-200:])
            p = subprocess.run([sys.executable, str(SCRIPT), SAMPLE, "--conversation", "x",
                                "--projects-root", str(ROOT), "--archive-dir", str(tmp14)],
                               capture_output=True, text=True, cwd=str(SCRIPT.parent))
            check("--conversation without --import-claude-ai is rejected",
                  p.returncode != 0 and "--import-claude-ai" in p.stderr, p.stderr[-200:])
            p = run(SAMPLE, "html,pdf", tmp14, extra=("--fragment",))
            check("--fragment with pdf is rejected before anything is written",
                  p.returncode != 0 and not list(tmp14.glob("*.html")),
                  f"rc={p.returncode} files={[f.name for f in tmp14.iterdir()]}")
            p = run(SAMPLE, "html", tmp14, extra=("--out", str(tmp14 / "stem.txt")))
            check("--out is treated as a stem: html lands in stem.html",
                  (tmp14 / "stem.html").exists() and not (tmp14 / "stem.txt").exists(),
                  str([f.name for f in tmp14.iterdir()]))
            p = subprocess.run([sys.executable, str(SCRIPT), "--version"],
                               capture_output=True, text=True, cwd=str(SCRIPT.parent))
            check("--version prints the archiver version",
                  p.returncode == 0 and ta.VERSION in p.stdout, p.stdout + p.stderr)
            p = subprocess.run([sys.executable, str(SCRIPT), "--help"],
                               capture_output=True, text=True, cwd=str(SCRIPT.parent))
            check("--help describes the current tool, not the v1 changelog",
                  "Markdown" in p.stdout and "vs v1" not in p.stdout
                  and "four formats" not in p.stdout, p.stdout[:300])
            check("--help carries no personal archive path",
                  "CLAUDE_CONVERSATIONS" not in p.stdout, "personal default path")
        finally:
            shutil.rmtree(tmp14, ignore_errors=True)

        # ------------------------------------------------------------------
        print("\n[25] A human prompt in list content keeps its P tag")
        tmp15 = pathlib.Path(tempfile.mkdtemp(prefix="ta-test25-"))
        try:
            src = tmp15 / "s.jsonl"
            src.write_text(json.dumps({
                "type": "user", "uuid": "l-1", "timestamp": "2026-02-01T10:00:00Z",
                "promptSource": "typed", "origin": {"kind": "human"},
                "message": {"role": "user", "content": [
                    {"type": "text", "text": "HUMAN-LIST-MARKER hello"},
                    {"type": "image", "source": {"type": "base64",
                                                 "media_type": "image/png", "data": "AAAA"}}]}})
                + "\n", encoding="utf-8")
            t25 = ta.parse_transcript(src, 4000)
            check("typed text beside an image is a human turn, not injected",
                  any(x["kind"] == "human" and "HUMAN-LIST-MARKER" in x["text"]
                      for x in t25.turns), str([x["kind"] for x in t25.turns]))
        finally:
            shutil.rmtree(tmp15, ignore_errors=True)

        # ------------------------------------------------------------------
        # Found by the 2026-08-28 survival run on a 5,693-record session:
        # worktree bookkeeping records Claude Code started writing in 2.1.x.
        # They carry no transcript content and must be classed as metadata,
        # not reported as "unhandled".
        print("\n[25b] Worktree bookkeeping records are metadata, not unhandled")
        tmp15b = pathlib.Path(tempfile.mkdtemp(prefix="ta-test25b-"))
        try:
            src = tmp15b / "w.jsonl"
            src.write_text("\n".join(json.dumps(r) for r in (
                {"type": "atis-latch", "atis": "", "sessionId": "w"},
                {"type": "relocated", "sessionId": "w", "relocatedCwd": "/tmp/x"},
                {"type": "worktree-state", "sessionId": "w",
                 "worktreeSession": {"worktreeName": "slice"}})) + "\n", encoding="utf-8")
            t25b = ta.parse_transcript(src, 4000)
            check("worktree record types are counted as metadata",
                  not any("unhandled" in k for k in t25b.counted_only)
                  and sum(v for k, v in t25b.counted_only.items() if k.startswith("metadata:")) == 3,
                  str(dict(t25b.counted_only)))
        finally:
            shutil.rmtree(tmp15b, ignore_errors=True)

        # ------------------------------------------------------------------
        # Found on 2026-08-31 in a real Fable 5 session: the harness refused a
        # message, retracted five assistant messages (absent from the .jsonl),
        # and continued on a fallback model. The page must say all of that as
        # structure, not only as the notice's prose; and the same session's
        # "away_summary" recap is a system record of its own.
        print("\n[25g] Safeguard refusal with model fallback: a structured event; retractions reported")
        tmp15c = pathlib.Path(tempfile.mkdtemp(prefix="ta-test25c-"))
        try:
            proj = tmp15c / "projects" / "p"
            proj.mkdir(parents=True)
            SIDC = "25c25c25-0000-4000-8000-000000000025"
            base = {"sessionId": SIDC, "isSidechain": False, "cwd": "/w", "version": "2.1.251"}
            recs = [
                dict(base, type="user", uuid="u-1", timestamp="2026-08-31T03:40:00Z",
                     promptSource="typed", origin={"kind": "human"},
                     message={"role": "user", "content": "start please"}),
                dict(base, type="assistant", uuid="a-1", timestamp="2026-08-31T03:40:10Z",
                     requestId="r1", message={"role": "assistant", "model": "claude-fable-5",
                                              "content": [{"type": "text", "text": "BEFORE-FALLBACK"}],
                                              "usage": {"input_tokens": 1, "output_tokens": 1}}),
                dict(base, type="user", uuid="u-ref", timestamp="2026-08-31T03:41:00Z",
                     promptSource="typed", origin={"kind": "human"},
                     message={"role": "user", "content": "go again"}),
                dict(base, type="system", uuid="s-fb", timestamp="2026-08-31T03:49:02Z",
                     subtype="model_refusal_fallback", level="warning", trigger="refusal",
                     content="Fable 5's safeguards flagged this message. Switched to Opus 4.8.",
                     originalModel="claude-fable-5", fallbackModel="claude-opus-4-8",
                     apiRefusalCategory="cyber", refusedUserMessageUuid="u-ref",
                     retractedMessageUuids=["gone-1", "gone-2", "gone-3", "gone-4", "gone-5"]),
                dict(base, type="assistant", uuid="a-2", timestamp="2026-08-31T03:49:31Z",
                     requestId="r2", message={"role": "assistant", "model": "claude-opus-4-8",
                                              "content": [{"type": "text", "text": "AFTER-FALLBACK"}],
                                              "usage": {"input_tokens": 1, "output_tokens": 1}}),
                dict(base, type="system", uuid="s-aw", timestamp="2026-08-31T03:50:00Z",
                     subtype="away_summary", content="AWAY-RECAP shipped it all"),
            ]
            srcc = proj / f"{SIDC}.jsonl"
            srcc.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
            t25c = ta.parse_transcript(srcc, 4000)
            ev = [x for x in t25c.turns if x["kind"] == "system_record"
                  and x.get("subtype") == "model_refusal_fallback"]
            check("the refusal fallback record renders as exactly one event",
                  len(ev) == 1, str([x.get("subtype") for x in t25c.turns if x["kind"] == "system_record"]))
            ev0 = ev[0] if ev else {"badge": "", "detail": "", "text": ""}
            check("its badge names the safeguard refusal, not the raw subtype",
                  ev0["badge"] == "Model fallback after a safeguard refusal", ev0["badge"])
            check("its detail states the model switch and the category",
                  "claude-fable-5 -> claude-opus-4-8" in ev0["detail"] and "cyber" in ev0["detail"],
                  ev0["detail"])
            check("its body says how many messages were retracted and that they are absent",
                  "5 message" in ev0["text"] and "not in the source" in ev0["text"], ev0["text"][-160:])
            check("retractions are tallied on the transcript",
                  sum(r["retracted"] for r in getattr(t25c, "retractions", [])) == 5,
                  str(getattr(t25c, "retractions", None)))
            aw = [x for x in t25c.turns if x["kind"] == "system_record" and x.get("subtype") == "away_summary"]
            check("an away_summary record renders with its own badge and text",
                  bool(aw) and aw[0]["badge"] == "Away summary" and "AWAY-RECAP" in aw[0]["text"],
                  str(aw[:1]))
            outc = tmp15c / "out"
            pc = subprocess.run([sys.executable, str(SCRIPT), SIDC, "--format", "html,text,markdown",
                                 "--archive-dir", str(outc), "--projects-root", str(tmp15c / "projects"),
                                 "--quiet"], capture_output=True, text=True, cwd=str(SCRIPT.parent))
            check("html/text/markdown render the fallback session", pc.returncode == 0,
                  pc.stderr.strip()[-300:])
            htmls = list(outc.glob("*.html"))
            hbody = htmls[0].read_text(encoding="utf-8", errors="replace") if htmls else ""
            check("the HTML session info carries a Harness retractions row",
                  "Harness retractions" in hbody and "5 message" in hbody, str([f.name for f in htmls]))
            for ext in ("txt", "md"):
                fs = list(outc.glob(f"*.{ext}"))
                body = fs[0].read_text(encoding="utf-8", errors="replace") if fs else ""
                check(f"the {ext} export carries the model switch and the retraction count",
                      "claude-fable-5 -> claude-opus-4-8" in body and "5 message" in body,
                      str([f.name for f in fs]))
        finally:
            shutil.rmtree(tmp15c, ignore_errors=True)

        # ------------------------------------------------------------------
        # Found by the 2026-08-28 archive refresh (Claude Code 2.1.9x): a
        # running cost/usage snapshot and two artifact-comment bookkeeping
        # records. No transcript content; metadata, not "unhandled".
        print("\n[25c] Cost-state and artifact-monitor records are metadata, not unhandled")
        tmp15c = pathlib.Path(tempfile.mkdtemp(prefix="ta-test25c-"))
        try:
            src = tmp15c / "c.jsonl"
            src.write_text("\n".join(json.dumps(r) for r in (
                {"type": "cost-state", "sessionId": "c", "totalCostUSD": 1.5,
                 "totalDuration": 10, "modelUsage": {}, "hasUnknownModelCost": False},
                {"type": "artifact-comment-monitor", "v": 1, "sessionId": "c",
                 "artifacts": {"a1": {"state": "armed", "title": "T"}}},
                {"type": "artifact-autoreact-ledger", "v": 1, "sessionId": "c",
                 "accountUuid": "acct", "artifacts": {"a1": {"threads": []}}})) + "\n",
                encoding="utf-8")
            t25c = ta.parse_transcript(src, 4000)
            check("cost-state and artifact-monitor types are counted as metadata",
                  not any("unhandled" in k for k in t25c.counted_only)
                  and sum(v for k, v in t25c.counted_only.items() if k.startswith("metadata:")) == 3,
                  str(dict(t25c.counted_only)))
        finally:
            shutil.rmtree(tmp15c, ignore_errors=True)

        # ------------------------------------------------------------------
        # cost-state is Claude Code's own running cost meter. It is written per
        # *process*: every `claude --resume` starts a fresh counter with a new
        # startTime, and older runs (before the record existed) wrote none. So
        # the reported cost is the sum of the last snapshot per startTime, and
        # it is partial when the session began before the first covered run.
        print("\n[25d] cost-state: Claude Code's reported cost, deduped per run, coverage flagged")
        tmp15d = pathlib.Path(tempfile.mkdtemp(prefix="ta-test25d-"))
        try:
            def cs(start_ms, usd, added=0, removed=0, unknown=False, sid="d"):
                return {"type": "cost-state", "sessionId": sid, "totalCostUSD": usd,
                        "totalLinesAdded": added, "totalLinesRemoved": removed,
                        "totalDuration": 1, "startTime": start_ms,
                        "modelUsage": {"claude-fable-5": {"costUSD": usd * 0.9},
                                       "claude-haiku-4-5-20251001": {"costUSD": usd * 0.1}},
                        "hasUnknownModelCost": unknown}
            # run A: two snapshots (cumulative, keep the last); run B: one.
            recs = [cs(1_000_000, 1.0, 5, 1), cs(1_000_000, 2.5, 10, 2), cs(2_000_000, 4.0, 7, 0)]
            src = tmp15d / "d.jsonl"
            src.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
            t25d = ta.parse_transcript(src, 4000)
            rc = ta.reported_cost(t25d)
            check("reported cost sums the last snapshot of each run",
                  rc is not None and abs(rc["usd"] - 6.5) < 1e-9 and rc["runs"] == 2, str(rc))
            check("reported cost is split per model across runs",
                  rc is not None and abs(rc["by_model"]["claude-fable-5"] - 5.85) < 1e-9
                  and abs(rc["by_model"]["claude-haiku-4-5-20251001"] - 0.65) < 1e-9, str(rc))
            check("lines added/removed follow the same per-run rule",
                  rc is not None and rc["lines_added"] == 17 and rc["lines_removed"] == 2, str(rc))
            check("no cost-state -> no reported cost",
                  ta.reported_cost(ta.parse_transcript(source_of(SAMPLE), 4000)) is None)
            # coverage: first run started at t=1000s; a session whose first
            # record is 10 minutes older has uncovered spend.
            t_early = datetime.datetime.fromtimestamp(1_000_000 / 1000 - 600, datetime.timezone.utc)
            t_same = datetime.datetime.fromtimestamp(1_000_000 / 1000 + 5, datetime.timezone.utc)
            check("coverage is partial when the session predates the first run",
                  ta.reported_cost(t25d, started=t_early)["partial"] is True)
            check("coverage is complete when the session starts with the first run",
                  ta.reported_cost(t25d, started=t_same)["partial"] is False)

            # End to end: page, embedded metadata, index.
            proj = tmp15d / "projects" / "p"
            proj.mkdir(parents=True)
            SID = "dddddddd-0000-4000-8000-000000000001"
            base = [{"type": "user", "uuid": "u1", "sessionId": SID,
                     "timestamp": "1970-01-01T00:16:41Z", "promptSource": "typed",
                     "origin": {"kind": "human"},
                     "message": {"role": "user", "content": "hello"}},
                    {"type": "assistant", "uuid": "a1", "sessionId": SID,
                     "timestamp": "1970-01-01T00:16:42Z", "requestId": "r1",
                     "message": {"role": "assistant", "model": "claude-fable-5",
                                 "content": [{"type": "text", "text": "hi"}],
                                 "usage": {"input_tokens": 10, "output_tokens": 10}}}]
            (proj / f"{SID}.jsonl").write_text(
                "\n".join(json.dumps(r) for r in base + [cs(1_000_000, 2.5, sid=SID),
                                                          cs(2_000_000, 4.0, sid=SID)]) + "\n",
                encoding="utf-8")
            out25d = tmp15d / "out"
            p = subprocess.run([sys.executable, str(SCRIPT), SID, "--format", "html,text,markdown",
                                "--projects-root", str(tmp15d / "projects"),
                                "--archive-dir", str(out25d)],
                               capture_output=True, text=True, cwd=str(SCRIPT.parent))
            check("cost-state export exits 0", p.returncode == 0, p.stderr[-300:])
            page = "".join(f.read_text(encoding="utf-8", errors="replace")
                           for f in out25d.glob("*.html")) if out25d.exists() else ""
            m = re.search(r'id="archive-meta">(.*?)</script>', page, re.S)
            meta = json.loads(m.group(1)) if m else {}
            check("metadata carries the reported cost and its coverage",
                  meta.get("reported_cost_usd") == 6.5 and meta.get("reported_cost_runs") == 2
                  and meta.get("reported_cost_partial") is False, str({k: v for k, v in meta.items() if "cost" in k}))
            check("metadata keeps the list-price estimate alongside",
                  isinstance(meta.get("list_cost_usd"), (int, float)), str(meta.get("list_cost_usd")))
            check("HTML page shows the reported figure with its source",
                  "$6.50" in page and "reported by Claude Code" in page, "figure missing")
            txt = "".join(f.read_text(encoding="utf-8", errors="replace")
                          for f in list(out25d.glob("*.txt")) + list(out25d.glob("*.md")))
            check("text and markdown carry the reported cost too",
                  txt.count("$6.50") >= 2, str(txt.count("$6.50")))
            p = subprocess.run([sys.executable, str(SCRIPT), "--index",
                                "--projects-root", str(tmp15d / "projects"),
                                "--archive-dir", str(out25d)],
                               capture_output=True, text=True, cwd=str(SCRIPT.parent))
            idx = (out25d / "index.html").read_text(encoding="utf-8", errors="replace")
            check("index prefers the reported cost when coverage is complete",
                  "$6.50 reported" in idx, "index still shows list price only")

            # Partial coverage: session records predate the first run by an hour.
            SID2 = "dddddddd-0000-4000-8000-000000000002"
            early = [dict(r, sessionId=SID2, timestamp="1970-01-01T00:00:01Z") for r in base]
            (proj / f"{SID2}.jsonl").write_text(
                "\n".join(json.dumps(r) for r in early + [cs(1_000_000, 2.5, sid=SID2)]) + "\n",
                encoding="utf-8")
            p = subprocess.run([sys.executable, str(SCRIPT), SID2, "--format", "html",
                                "--projects-root", str(tmp15d / "projects"),
                                "--archive-dir", str(out25d)],
                               capture_output=True, text=True, cwd=str(SCRIPT.parent))
            page2 = "".join(f.read_text(encoding="utf-8", errors="replace")
                            for f in out25d.glob(f"{SID2}*.html"))
            m2 = re.search(r'id="archive-meta">(.*?)</script>', page2, re.S)
            meta2 = json.loads(m2.group(1)) if m2 else {}
            check("partial coverage is flagged in metadata and on the page",
                  meta2.get("reported_cost_partial") is True and "not covered" in page2,
                  str(meta2.get("reported_cost_partial")))
            subprocess.run([sys.executable, str(SCRIPT), "--index",
                            "--projects-root", str(tmp15d / "projects"),
                            "--archive-dir", str(out25d)], capture_output=True, text=True,
                           cwd=str(SCRIPT.parent))
            idx = (out25d / "index.html").read_text(encoding="utf-8", errors="replace")
            row2 = idx[idx.find(f'data-k="{SID2}"'):][:1500]
            check("index falls back to list price when coverage is partial",
                  "at list price" in row2 and "reported" not in row2, row2[:200])
        finally:
            shutil.rmtree(tmp15d, ignore_errors=True)

        # ------------------------------------------------------------------
        # 2026-08-28 code review of 2.5: the meter must be gathered from every
        # file in a session chain (a continuation file does not repeat the
        # earlier run's cost-state), every format must state coverage, and a
        # malformed cost-state record must never abort the export.
        print("\n[25e] Reported cost: chain merge, every format, malformed records")
        tmp15e = pathlib.Path(tempfile.mkdtemp(prefix="ta-test25e-"))
        try:
            def cs2(start_ms, usd, sid, **extra):
                r = {"type": "cost-state", "sessionId": sid, "totalCostUSD": usd,
                     "totalLinesAdded": 0, "totalLinesRemoved": 0, "totalDuration": 1,
                     "startTime": start_ms,
                     "modelUsage": {"claude-fable-5": {"costUSD": usd}}}
                r.update(extra)
                return r
            proj = tmp15e / "projects" / "p"
            proj.mkdir(parents=True)
            B_ID = "eeeeeeee-0000-4000-8000-000000000001"
            C_ID = "eeeeeeee-0000-4000-8000-000000000002"
            convo = [{"type": "user", "uuid": f"e{i}", "sessionId": B_ID,
                      "timestamp": f"1970-01-01T00:16:{41 + i:02d}Z", "promptSource": "typed",
                      "origin": {"kind": "human"},
                      "message": {"role": "user", "content": f"prompt {i}"}} for i in range(6)]
            later = [{"type": "user", "uuid": f"l{i}", "sessionId": C_ID,
                      "timestamp": f"1970-01-01T00:33:{20 + i:02d}Z", "promptSource": "typed",
                      "origin": {"kind": "human"},
                      "message": {"role": "user", "content": f"later {i}"}} for i in range(3)]
            # run A ($2.50) is only in the first file; run B ($4.00) only in the continuation
            (proj / f"{B_ID}.jsonl").write_text(
                "\n".join(json.dumps(r) for r in convo + [cs2(1_000_000, 2.5, B_ID)]) + "\n",
                encoding="utf-8")
            (proj / f"{C_ID}.jsonl").write_text(
                "\n".join(json.dumps(r) for r in convo + later + [cs2(2_000_000, 4.0, C_ID)]) + "\n",
                encoding="utf-8")
            out15e = tmp15e / "out"
            p = subprocess.run([sys.executable, str(SCRIPT), B_ID, "--format", "html,text,markdown,latex",
                                "--projects-root", str(tmp15e / "projects"),
                                "--archive-dir", str(out15e)],
                               capture_output=True, text=True, cwd=str(SCRIPT.parent))
            check("chained cost export exits 0", p.returncode == 0, p.stderr[-300:])
            page = "".join(f.read_text(encoding="utf-8", errors="replace")
                           for f in out15e.glob("*.html")) if out15e.exists() else ""
            m = re.search(r'id="archive-meta">(.*?)</script>', page, re.S)
            meta = json.loads(m.group(1)) if m else {}
            check("reported cost merges every run in the session chain",
                  meta.get("reported_cost_usd") == 6.5 and meta.get("reported_cost_runs") == 2,
                  str({k: v for k, v in meta.items() if "cost" in k}))
            check("chain-merged coverage is complete, not partial",
                  meta.get("reported_cost_partial") is False, str(meta.get("reported_cost_partial")))

            # Partial coverage must be stated in text, markdown and LaTeX too.
            P_ID = "eeeeeeee-0000-4000-8000-000000000003"
            early = [dict(r, sessionId=P_ID, uuid="p" + r["uuid"], timestamp="1970-01-01T00:00:01Z")
                     for r in convo]
            (proj / f"{P_ID}.jsonl").write_text(
                "\n".join(json.dumps(r) for r in early + [cs2(1_000_000, 2.5, P_ID)]) + "\n",
                encoding="utf-8")
            p = subprocess.run([sys.executable, str(SCRIPT), P_ID, "--format", "text,markdown,latex",
                                "--projects-root", str(tmp15e / "projects"),
                                "--archive-dir", str(out15e)],
                               capture_output=True, text=True, cwd=str(SCRIPT.parent))
            check("partial-coverage export exits 0", p.returncode == 0, p.stderr[-300:])
            for ext in ("txt", "md", "tex"):
                body = "".join(f.read_text(encoding="utf-8", errors="replace")
                               for f in out15e.glob(f"{P_ID}*.{ext}"))
                check(f"{ext} states the reported cost and its partial coverage",
                      "2.50" in body and "reported by Claude Code" in body
                      and "not covered" in body, body[:400])

            # Malformed cost-state records: skipped, never fatal.
            M_ID = "eeeeeeee-0000-4000-8000-000000000004"
            bad = [cs2(1_000_000, 1.0, M_ID, modelUsage={"claude-fable-5": 0.5}),
                   cs2(1_500_000, 1.0, M_ID, modelUsage=[]),
                   cs2(float("nan"), 1.0, M_ID),
                   cs2(2_000_000, 2.0, M_ID)]
            src = tmp15e / "m.jsonl"
            src.write_text("\n".join(json.dumps(r) for r in bad) + "\n", encoding="utf-8")
            try:
                tm = ta.parse_transcript(src, 4000)
                rcm = ta.reported_cost(tm)
                check("malformed cost-state records do not abort the export",
                      rcm is not None and abs(rcm["usd"] - 4.0) < 1e-9 and rcm["runs"] == 3, str(rcm))
            except Exception as e:
                check("malformed cost-state records do not abort the export", False, repr(e))
        finally:
            shutil.rmtree(tmp15e, ignore_errors=True)

        # ------------------------------------------------------------------
        # A session resumed after /compact: the continuation file carries every
        # exchange but not the old file's compaction tail (attachments, the
        # compact_boundary, the summary record, the /compact command). Those
        # are bookkeeping, not conversation, so the continuation must still
        # count as the same conversation continued -- seen on a real pair
        # where 18 such records made the tool call it a fork.
        print("\n[25f] A post-compaction resume is a continuation, not a fork")
        tmp15f = pathlib.Path(tempfile.mkdtemp(prefix="ta-test25f-"))
        try:
            proj = tmp15f / "projects" / "p"
            proj.mkdir(parents=True)
            OLD = "ffffffff-0000-4000-8000-000000000001"
            NEW = "ffffffff-0000-4000-8000-000000000002"
            convo = []
            for i in range(30):
                convo.append({"type": "user", "uuid": f"h{i}", "sessionId": OLD,
                              "timestamp": f"2026-02-01T10:{i:02d}:00Z", "promptSource": "typed",
                              "origin": {"kind": "human"},
                              "message": {"role": "user", "content": f"prompt {i}"}})
                convo.append({"type": "assistant", "uuid": f"a{i}", "sessionId": OLD,
                              "timestamp": f"2026-02-01T10:{i:02d}:30Z", "requestId": f"r{i}",
                              "message": {"role": "assistant", "model": "claude-fable-5",
                                          "content": [{"type": "text", "text": f"answer {i}"}],
                                          "usage": {"input_tokens": 1, "output_tokens": 1}}})
            tail = [{"type": "attachment", "uuid": f"att{i}", "sessionId": OLD,
                     "timestamp": "2026-02-01T11:00:00Z",
                     "attachment": {"type": "hook_success", "hookName": "x", "exitCode": 0}}
                    for i in range(12)]
            tail += [{"type": "user", "uuid": "cmd1", "sessionId": OLD,
                      "timestamp": "2026-02-01T11:01:00Z", "promptSource": "system",
                      "message": {"role": "user", "content": "<command-name>/compact</command-name>"}},
                     {"type": "system", "uuid": "cb1", "sessionId": OLD, "subtype": "compact_boundary",
                      "timestamp": "2026-02-01T11:01:05Z", "content": "",
                      "compactMetadata": {"trigger": "manual", "preTokens": 100, "postTokens": 10}},
                     {"type": "user", "uuid": "sum1", "sessionId": OLD, "isCompactSummary": True,
                      "timestamp": "2026-02-01T11:01:06Z",
                      "message": {"role": "user", "content": "This session is being continued from a previous conversation"}}]
            cost_a = {"type": "cost-state", "sessionId": OLD, "totalCostUSD": 2.5,
                      "startTime": 1769940000000, "modelUsage": {"claude-fable-5": {"costUSD": 2.5}}}
            later = [{"type": "user", "uuid": f"l{i}", "sessionId": NEW,
                      "timestamp": f"2026-02-01T12:{i:02d}:00Z", "promptSource": "typed",
                      "origin": {"kind": "human"},
                      "message": {"role": "user", "content": f"later {i}"}} for i in range(5)]
            cost_b = {"type": "cost-state", "sessionId": NEW, "totalCostUSD": 4.0,
                      "startTime": 1769947200000, "modelUsage": {"claude-fable-5": {"costUSD": 4.0}}}
            (proj / f"{OLD}.jsonl").write_text(
                "\n".join(json.dumps(r) for r in convo + tail + [cost_a]) + "\n", encoding="utf-8")
            (proj / f"{NEW}.jsonl").write_text(
                "\n".join(json.dumps(r) for r in convo + later + [cost_b]) + "\n", encoding="utf-8")
            ss = ta.scan_sessions(tmp15f / "projects")
            best, rel = ta.resolve_chain(OLD, ss)
            check("post-compaction continuation is classed as a superset",
                  rel and rel[0]["relation"] == "superset", str(rel))
            check("post-compaction continuation is followed", best == NEW, best[:8])
            check("bookkeeping-only drop count is still reported",
                  rel and rel[0]["dropped"] == 15, str(rel))
            # A genuine fork (conversation diverged) must still be refused.
            FORK = "ffffffff-0000-4000-8000-000000000003"
            # shares 40 of the 60 exchange records (overlap 0.53, above the
            # 0.5 gate) but lacks the last 10 exchanges: diverged, not continued.
            div = convo[:40] + [{"type": "user", "uuid": f"f{i}", "sessionId": FORK,
                                 "timestamp": f"2026-02-01T13:{i:02d}:00Z", "promptSource": "typed",
                                 "origin": {"kind": "human"},
                                 "message": {"role": "user", "content": f"elsewhere {i}"}}
                                for i in range(40)]
            (proj / f"{FORK}.jsonl").write_text(
                "\n".join(json.dumps(r) for r in div) + "\n", encoding="utf-8")
            ss = ta.scan_sessions(tmp15f / "projects")
            best2, rel2 = ta.resolve_chain(OLD, ss)
            check("a diverged conversation is still a fork and not followed",
                  best2 == NEW and any(r["session_id"] == FORK and r["relation"] == "fork" for r in rel2),
                  str([(r["session_id"][:8], r["relation"]) for r in rel2]))
            out15f = tmp15f / "out"
            p = subprocess.run([sys.executable, str(SCRIPT), OLD, "--format", "html",
                                "--projects-root", str(tmp15f / "projects"),
                                "--archive-dir", str(out15f)],
                               capture_output=True, text=True, cwd=str(SCRIPT.parent))
            page = "".join(f.read_text(encoding="utf-8", errors="replace")
                           for f in out15f.glob("*.html")) if out15f.exists() else ""
            m = re.search(r'id="archive-meta">(.*?)</script>', page, re.S)
            meta = json.loads(m.group(1)) if m else {}
            check("archiving the old id yields the continuation with both cost runs",
                  meta.get("session_id") == NEW and meta.get("reported_cost_usd") == 6.5
                  and meta.get("reported_cost_partial") is False,
                  str({k: meta.get(k) for k in ("session_id", "reported_cost_usd", "reported_cost_partial")}))
        finally:
            shutil.rmtree(tmp15f, ignore_errors=True)

        # ------------------------------------------------------------------
        print("\n[26] Subagents of the requested session survive chain resolution")
        tmp16 = pathlib.Path(tempfile.mkdtemp(prefix="ta-test26-"))
        try:
            proj = tmp16 / "projects" / "p"
            proj.mkdir(parents=True)
            BASE_ID = "aaaaaaaa-0000-4000-8000-000000000001"
            CONT_ID = "bbbbbbbb-0000-4000-8000-000000000002"
            base_recs = [{"type": "user", "uuid": f"u{i}", "sessionId": BASE_ID,
                          "timestamp": f"2026-02-01T10:00:{i:02d}Z", "promptSource": "typed",
                          "origin": {"kind": "human"},
                          "message": {"role": "user", "content": f"prompt {i}"}}
                         for i in range(10)]
            cont_recs = base_recs + [{"type": "user", "uuid": f"c{i}", "sessionId": CONT_ID,
                                      "timestamp": f"2026-02-01T11:00:{i:02d}Z",
                                      "promptSource": "typed", "origin": {"kind": "human"},
                                      "message": {"role": "user", "content": f"later {i}"}}
                                     for i in range(5)]
            (proj / f"{BASE_ID}.jsonl").write_text(
                "\n".join(json.dumps(r) for r in base_recs) + "\n", encoding="utf-8")
            (proj / f"{CONT_ID}.jsonl").write_text(
                "\n".join(json.dumps(r) for r in cont_recs) + "\n", encoding="utf-8")
            agd = proj / BASE_ID / "subagents"
            agd.mkdir(parents=True)
            (agd / "agent-0000000000000abc.jsonl").write_text(json.dumps({
                "type": "assistant", "uuid": "ag-1", "timestamp": "2026-02-01T10:30:00Z",
                "requestId": "r-ag", "message": {"role": "assistant", "model": "claude-sonnet-5",
                "content": [{"type": "text", "text": "CHAINED-SUBAGENT-MARKER"}],
                "usage": {"input_tokens": 1, "output_tokens": 1}}}) + "\n", encoding="utf-8")
            out16 = tmp16 / "out"
            p = subprocess.run([sys.executable, str(SCRIPT), BASE_ID, "--format", "html",
                                "--projects-root", str(tmp16 / "projects"),
                                "--archive-dir", str(out16)],
                               capture_output=True, text=True, cwd=str(SCRIPT.parent))
            check("chained export exits 0", p.returncode == 0, p.stderr[-300:])
            body = "".join(f.read_text(encoding="utf-8", errors="replace")
                           for f in out16.glob("*.html")) if out16.exists() else ""
            check("the continuation is archived", "later 4" in body, "continuation missing")
            check("subagents filed under the earlier id are rendered",
                  "CHAINED-SUBAGENT-MARKER" in body, "subagent lost across the chain")
        finally:
            shutil.rmtree(tmp16, ignore_errors=True)

        # ------------------------------------------------------------------
        print("\n[27] Logging: audit log per run, --quiet, --log-dir")
        tmp17 = pathlib.Path(tempfile.mkdtemp(prefix="ta-test27-"))
        try:
            p = run(SAMPLE, "html", tmp17, extra=("--quiet",))
            check("--quiet export exits 0", p.returncode == 0, p.stderr[-300:])
            check("--quiet prints nothing on stdout", p.stdout.strip() == "", p.stdout[:200])
            logs = list((tmp17 / "logs").glob("*.log")) if (tmp17 / "logs").exists() else []
            check("an audit log is written under <archive-dir>/logs/", len(logs) == 1,
                  str([f.name for f in logs]))
            if logs:
                lg = logs[0].read_text(encoding="utf-8", errors="replace")
                check("audit log records the command line and version",
                      "--quiet" in lg and ta.VERSION in lg, lg[:300])
                check("audit log records the outcome", "outcome" in lg.lower(), lg[-300:])
            alt = tmp17 / "elsewhere"
            p = run(SAMPLE, "text", tmp17, extra=("--log-dir", str(alt)))
            check("--log-dir relocates the audit log",
                  alt.exists() and len(list(alt.glob("*.log"))) == 1,
                  str(list(alt.glob("*")) if alt.exists() else "no dir"))
            p = run(SAMPLE, "text", tmp17, extra=("--verbose",))
            check("--verbose exits 0 and says more than the default",
                  p.returncode == 0 and len(p.stdout) > 0, p.stderr[-200:])
        finally:
            shutil.rmtree(tmp17, ignore_errors=True)

        # ------------------------------------------------------------------
        print("\n[28] HTML page: theme toggle and turn search")
        tmp18 = pathlib.Path(tempfile.mkdtemp(prefix="ta-test28-"))
        try:
            p = run(SAMPLE, "html", tmp18)
            page = next(iter(tmp18.glob("*.html"))).read_text(encoding="utf-8",
                                                               errors="replace")
            check("page has a theme toggle", 'id="theme-toggle"' in page, "no toggle")
            js = page.split("<script>")[-1]
            check("toggle sets data-theme on the root element",
                  "data-theme" in js and "theme-toggle" in js, "no theme JS")
            check("page has a turn search box", 'id="search"' in page, "no search box")
            check("search JS filters turns by content",
                  "getElementById('search')" in js and ".turn" in js, "no search JS")
        finally:
            shutil.rmtree(tmp18, ignore_errors=True)

        # ------------------------------------------------------------------
        # Review #2 (2026-08-28): --index into an archive dir that does not
        # exist yet crashed (build() creates its directory; build_index did
        # not), and the last roadmap gap -- searching every archive from the
        # index page -- gets a prompt index embedded in index.html.
        print("\n[30] --index creates the archive directory and indexes prompts across archives")
        tmp30 = pathlib.Path(tempfile.mkdtemp(prefix="ta-test30-"))
        try:
            fresh = tmp30 / "does" / "not" / "exist"
            p = subprocess.run([sys.executable, str(SCRIPT), "--index",
                                "--archive-dir", str(fresh), "--projects-root", str(ROOT)],
                               capture_output=True, text=True, cwd=str(SCRIPT.parent))
            check("--index into a missing archive dir exits 0", p.returncode == 0, p.stderr[-300:])
            check("--index created the directory and wrote index.html",
                  (fresh / "index.html").exists(), "no index.html")
            # archive two sessions (one paginated), then index; every human
            # prompt of every archive must be findable from the index page.
            arch = tmp30 / "arch"
            p = run(SAMPLE, "html", arch, extra=("--paginate", "4"))
            check("paginated sample archived", p.returncode == 0, p.stderr[-300:])
            SHOW = "0000c0de-cafe-4000-8000-00000000f00d"
            p = run(SHOW, "html", arch)
            check("showcase archived", p.returncode == 0, p.stderr[-300:])
            p = subprocess.run([sys.executable, str(SCRIPT), "--index",
                                "--archive-dir", str(arch), "--projects-root", str(ROOT)],
                               capture_output=True, text=True, cwd=str(SCRIPT.parent))
            check("index build exits 0", p.returncode == 0, p.stderr[-300:])
            idx = (arch / "index.html").read_text(encoding="utf-8", errors="replace")
            m = re.search(r'<script type="application/json" id="search-index">(.*?)</script>', idx, re.S)
            check("index embeds a search index", m is not None, "no search-index block")
            sidx = json.loads(m.group(1).replace("<\\/", "</")) if m else []
            texts = {(e["session_id"][:8], pr["tag"]): pr for e in sidx for pr in e["prompts"]}
            t30 = ta.parse_transcript(source_of(SAMPLE), 4000)
            ta.assign_tags(t30)
            wanted = [(SAMPLE[:8], x["tag"], x["text"]) for x in t30.turns if x["kind"] == "human"]
            missing = [tag for sid8, tag, _ in wanted if (sid8, tag) not in texts]
            check("every prompt of a paginated archive is in the search index (all pages)",
                  wanted and not missing, f"missing {missing}")
            found = [(texts.get((s, tg)) or {}, tg, tx) for s, tg, tx in wanted]
            check("search entries carry the prompt text",
                  not missing and all(e.get("text", "")[:40] == tx.strip()[:40] for e, _, tx in found),
                  "text mismatch")
            check("search entries deep-link to the page holding the prompt",
                  not missing and all(e.get("href", "").endswith(f"#{tg}") and
                                      (arch / e["href"].split("#")[0]).exists()
                                      for e, tg, _ in found),
                  str([e.get("href") for e, _, _ in found][:3]))
            check("showcase prompts are indexed too",
                  any(e["session_id"] == SHOW and e["prompts"] for e in sidx), "showcase missing")
            js = idx.split("<script>")[-1]
            check("index page has a cross-archive search box",
                  'id="archive-search"' in idx and "archive-search" in js, "no search UI")
            check("search results container exists", 'id="search-results"' in idx, "missing")
        finally:
            shutil.rmtree(tmp30, ignore_errors=True)

        # ------------------------------------------------------------------
        # Full LaTeX pass over 62 real sessions (2026-08-29): two failed with
        # "TeX capacity exceeded" -- a breakable tcolorbox holding a 9,614-line
        # verbatim turn. Measured: 4,000 lines in one box compiles, 9,614 does
        # not; the same block as consecutive 1,500-line boxes compiles. So a
        # huge verbatim turn is split into consecutive boxes, and the page says so.
        print("\n[31] Huge verbatim turns are split into consecutive LaTeX boxes")
        t31 = ta.Transcript()
        big_h = "\n".join(f"line {i} of a pasted log" for i in range(5000))
        big_o = "\n".join(f"out {i}" for i in range(4000))
        t31.turns = [
            {"kind": "human", "ts": "2026-02-01T10:00:00Z", "text": big_h, "html": "", "tag": "P1"},
            {"kind": "tool", "ts": "2026-02-01T10:00:01Z", "chip": "Bash", "label": "x",
             "tool_name": "Bash", "input": '{"command": "x"}', "output_text": big_o,
             "output_images": [], "is_error": False, "resolved": True},
            {"kind": "human", "ts": "2026-02-01T10:00:02Z", "text": "short", "html": "", "tag": "P2"},
        ]
        src31, tally31 = ta.emit_latex(t31, {"title": "t", "session_id": "s", "subtitle": "",
                                             "summary_text": "", "cost_note": ""}, tool_output=True)
        check("a 5,000-line human turn becomes 4 boxes",
              src31.count("\\begin{humanturn}") == 5, f"{src31.count(chr(92) + 'begin{humanturn}')} humanturn boxes")
        check("split boxes are numbered in their titles",
              "(part 1/4)" in src31 and "(part 4/4)" in src31, "no part numbering")
        check("a 4,000-line tool output becomes 3 boxes",
              src31.count("\\begin{toolturn}") == 3, f"{src31.count(chr(92) + 'begin{toolturn}')} toolturn boxes")
        blocks31 = re.findall(r"\\begin\{Verbatim\}\[[^\]]*\]\n(.*?)\n\\end\{Verbatim\}", src31, re.S)
        check("no Verbatim block exceeds the box limit",
              blocks31 and max(b.count("\n") + 1 for b in blocks31) <= ta._TEX_BOX_MAX_LINES,
              f"max {max((b.count(chr(10)) + 1 for b in blocks31), default=0)}")
        check("every line of the big turn survives the split",
              all(f"line {i} of a pasted log" in src31 for i in (0, 1499, 1500, 4999)), "lines lost")
        check("the split is counted and stated in the document",
              tally31["split_boxes"] == 2 and "split into consecutive boxes" in src31,
              f"tally={tally31['split_boxes']}")
        check("a short turn is still one box", src31.count("HUMAN - P2 ") == 1, "short turn split")

        # The tool's INPUT can be the huge payload too (a Write call carrying a
        # whole file), and real tool output ends in a newline: neither may
        # produce one oversized box or a spurious "(empty)" part.
        t32 = ta.Transcript()
        big_in = json.dumps({"file_path": "x.py", "content": "\n".join(f"src {i}" for i in range(3200))})
        t32.turns = [
            {"kind": "tool", "ts": "2026-02-01T10:00:01Z", "chip": "Write", "label": "x.py",
             "tool_name": "Write", "input": big_in, "output_text": "ok",
             "output_images": [], "is_error": False, "resolved": True},
            {"kind": "tool", "ts": "2026-02-01T10:00:02Z", "chip": "Bash", "label": "y",
             "tool_name": "Bash", "input": '{"command": "y"}',
             "output_text": "\n".join(f"row {i}" for i in range(ta._TEX_BOX_MAX_LINES - 1)) + "\n",
             "output_images": [{"data": ""}], "is_error": False, "resolved": True},
        ]
        src32, tally32 = ta.emit_latex(t32, {"title": "t", "session_id": "s", "subtitle": "",
                                             "summary_text": "", "cost_note": ""}, tool_output=True)
        blocks32 = re.findall(r"\\begin\{Verbatim\}\[[^\]]*\]\n(.*?)\n\\end\{Verbatim\}", src32, re.S)
        check("a huge tool input is split into boxes like a huge output",
              src32.count("\\begin{toolturn}") >= 4 and "(part 1/" in src32 and tally32["split_boxes"] == 1,
              f"{src32.count(chr(92) + 'begin{toolturn}')} boxes, tally={tally32['split_boxes']}")
        check("no Verbatim block exceeds the box limit when the input is the big part",
              blocks32 and max(b.count("\n") + 1 for b in blocks32) <= ta._TEX_BOX_MAX_LINES,
              f"max {max((b.count(chr(10)) + 1 for b in blocks32), default=0)}")
        check("the tool's output still follows its split input", "src 3199" in src32 and "ok" in src32, "lost")
        check("a trailing newline just over the limit does not add an '(empty)' part",
              "(part 2/2)" not in src32 and "(empty)" not in src32 and "row 1498" in src32,
              "spurious part or lost rows")
        check("the image note stays in the tool's own box, after its output",
              src32.count("[image omitted]") == 1 and "(images)" not in src32
              and src32.index("row 1498") < src32.index("[image omitted]"),
              "image note misplaced")

        # A Claude reply (or thinking) that prints a whole file in a fenced
        # block reaches the same "TeX capacity exceeded" through md_to_tex:
        # markdown turns must be packed into bounded boxes too, the fence
        # split across parts and the prose around it kept in order.
        t33 = ta.Transcript()
        big_code = "\n".join(f"def f{i}(): return {i}" for i in range(5000))
        t33.turns = [
            {"kind": "assistant", "ts": "2026-02-01T10:00:00Z", "tag": "R1",
             "text": "Here is the whole file:\n\n```python\n" + big_code + "\n```\n\nThat is all."},
            {"kind": "thinking", "ts": "2026-02-01T10:00:01Z",
             "text": "Let me recall it.\n\n```\n" + "\n".join(f"mem {i}" for i in range(3200)) + "\n```\n"},
            {"kind": "assistant", "ts": "2026-02-01T10:00:02Z", "tag": "R2", "text": "Done."},
        ]
        src33, tally33 = ta.emit_latex(t33, {"title": "t", "session_id": "s", "subtitle": "",
                                             "summary_text": "", "cost_note": ""}, tool_output=True)
        blocks33 = re.findall(r"\\begin\{Verbatim\}\[[^\]]*\]\n(.*?)\n\\end\{Verbatim\}", src33, re.S)
        check("a Claude reply with a 5,000-line code block becomes 4 boxes",
              src33.count("\\begin{claudeturn}") == 5 and "CLAUDE - R1 (part 1/4)" in src33
              and "(part 4/4)" in src33,
              f"{src33.count(chr(92) + 'begin{claudeturn}')} claudeturn boxes")
        check("a thinking turn with a huge code block is split too",
              src33.count("\\begin{thinkturn}") == 3 and "THINKING (part 3/3)" in src33,
              f"{src33.count(chr(92) + 'begin{thinkturn}')} thinkturn boxes")
        check("no Verbatim block of a markdown turn exceeds the box limit",
              blocks33 and max(b.count("\n") + 1 for b in blocks33) <= ta._TEX_BOX_MAX_LINES,
              f"max {max((b.count(chr(10)) + 1 for b in blocks33), default=0)}")
        check("the prose around the split fence survives in order",
              src33.index("Here is the whole file") < src33.index("def f0()")
              < src33.index("def f4999()") < src33.index("That is all"),
              "prose lost or reordered")
        check("markdown splits are counted with the verbatim ones",
              tally33["split_boxes"] == 2, f"tally={tally33['split_boxes']}")
        check("a short Claude reply is still one box",
              src33.count("CLAUDE - R2 ") == 1 and "R2 (part" not in src33, "short reply split")

        # ------------------------------------------------------------------
        # Project review 2026-08-29: a markdown table in a Claude reply went
        # into a plain tabular, which cannot break across a page and has no
        # width of its own. Measured in the compiled PDF: 100 rows -> 63
        # survived, 200 -> 22, 300 -> 0, and a 12-column table lost 35 of its
        # 60 cells off the right edge of the paper. xelatex exited 0 and
        # logged no warning, so neither this suite nor the 64-session pass
        # could see it; the .tex held every row, so the loss was at
        # typesetting. Tables are now cut into row chunks a breakable box can
        # break between, and wrap their cells when the natural width does not
        # fit the line.
        print("\n[34] Markdown tables survive typesetting")
        tally34 = collections.Counter()
        tall = "| a | b |\n|---|---|\n" + "\n".join(
            "| row%d | v%d |" % (i, i) for i in range(300))
        blocks34 = ta.md_to_tex_blocks(tall, tally34)
        src34 = "".join(blocks34)
        chunks34 = re.findall(r"\\begin\{tabular\}.*?\\end\{tabular\}", src34, re.S)
        check("a 300-row table is cut into several tabulars",
              len(chunks34) >= 6, "%d tabulars" % len(chunks34))
        check("no single tabular chunk exceeds the row-chunk limit",
              chunks34 and max(c.count("\\\\\n") for c in chunks34) <= ta._TEX_TABLE_MAX_LINES + 2,
              "max %d rows in a chunk" % max((c.count("\\\\\n") for c in chunks34), default=0))
        check("every row of the tall table is still in the source",
              all(("row%d" % i) in src34 for i in (0, 42, 150, 299)), "rows lost")
        check("each chunk repeats the header so it still reads as one table",
              src34.count("a & b") >= len(chunks34), "header not repeated per chunk")
        check("a continued chunk says it is continued",
              "continued" in src34.lower(), "no continuation marker")

        wide = ("| " + " | ".join("column_header_%d" % i for i in range(12)) + " |\n"
                + "|" + "---|" * 12 + "\n"
                + "\n".join("| " + " | ".join("WIDECELL%dlongvalue" % i for i in range(12)) + " |"
                            for _ in range(5)))
        src34w = "".join(ta.md_to_tex_blocks(wide, tally34))
        check("a table too wide for the line gets wrapping columns",
              "p{" in src34w and "\\begin{tabular}{llll" not in src34w,
              "still fixed-width l columns")
        check("every cell of the wide table is in the source",
              src34w.count("WIDECELL") == 60, "%d cells" % src34w.count("WIDECELL"))

        src34s = "".join(ta.md_to_tex_blocks("| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |", tally34))
        check("a small table is still one plain tabular",
              src34s.count("\\begin{tabular}") == 1 and "\\begin{tabular}{ll}" in src34s,
              "small table changed shape")

        # The packer costed an _Atomic block by its newlines alone, so a reply
        # that is one enormous unbroken paragraph costed two lines and went
        # into a single box -- the same TeX-capacity door 2.6.1 and 2.6.2
        # closed for pastes and fences, reached through prose instead.
        blocks34p = ta.md_to_tex_blocks("word " * 60000, tally34)
        check("one enormous paragraph is costed by its typeset length",
              sum(ta._atomic_cost(b) for b in blocks34p) > ta._TEX_BOX_MAX_LINES,
              "a 300,000-character paragraph still costs only its newlines")

        # A .tex holding every row proves nothing: the loss was downstream, in
        # the typesetting, and the run still exited 0. So the guard is the
        # compiled artefact -- a 300-row table has to occupy the pages its
        # rows need. Before the fix this document was 4 pages with no row on
        # any of them; after it, twelve.
        if not shutil.which("xelatex"):
            skip("a long table's rows reach the compiled PDF", "xelatex not on PATH")
            SKIPPED[0] += 1      # and the export check that precedes it
        else:
            tdir = pathlib.Path(tempfile.mkdtemp(prefix="tbl_"))
            try:
                sess = tdir / "proj" / "p"
                sess.mkdir(parents=True)
                sid = "dddddddd-0000-4000-8000-00000000table"[:36]
                u1 = "dddddddd-0000-4000-9000-000000000001"
                recs = [
                    {"type": "user", "uuid": u1, "parentUuid": None, "sessionId": sid,
                     "timestamp": "2026-02-01T10:00:00Z", "cwd": "/tmp", "version": "2.1.9",
                     "message": {"role": "user", "content": [{"type": "text", "text": "table"}]}},
                    {"type": "assistant", "uuid": "dddddddd-0000-4000-9000-000000000002",
                     "parentUuid": u1, "sessionId": sid, "timestamp": "2026-02-01T10:00:01Z",
                     "requestId": "r1", "cwd": "/tmp", "version": "2.1.9",
                     "message": {"role": "assistant", "model": "claude-opus-5",
                                 "content": [{"type": "text", "text": tall}],
                                 "usage": {"input_tokens": 10, "output_tokens": 20}}},
                ]
                (sess / (sid + ".jsonl")).write_text(
                    "\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
                q = subprocess.run(
                    [sys.executable, str(SCRIPT), sid, "--projects-root", str(tdir / "proj"),
                     "--archive-dir", str(tdir / "out"), "--format", "pdf",
                     "--tool-output", "off"], capture_output=True, text=True)
                built = list((tdir / "out").glob("*.pdf"))
                check("a session whose reply is a 300-row table exports to PDF",
                      q.returncode == 0 and len(built) == 1,
                      (q.stderr or "")[-300:])
                pages = pdf_page_count(built[0]) if built else 0
                check("the long table's rows reach the compiled PDF, not just the .tex",
                      pages >= 8,
                      "%d pages -- 300 rows cannot fit in that many unless they were dropped"
                      % pages)
            finally:
                shutil.rmtree(tdir, ignore_errors=True)

        # ------------------------------------------------------------------
        print("\n[29] Documentation set and its consistency with the CLI")
        REPO = HERE.parent
        for rel in ("AGENTS.md", "CHANGELOG.md", "docs/USER_MANUAL.md",
                    "docs/USER_MANUAL.html", "docs/USER_MANUAL.pdf", "docs/build_manual.py"):
            check(f"{rel} exists", (REPO / rel).exists(), "missing")
        for rel in ("AGENTS.md", "CHANGELOG.md", "docs/USER_MANUAL.md"):
            check(f"{rel} is not swallowed by .gitignore",
                  subprocess.run(["git", "check-ignore", "-q", rel],
                                 cwd=str(REPO)).returncode != 0, "ignored")
        readme = (REPO / "README.md").read_text(encoding="utf-8", errors="replace")
        manual = (REPO / "docs" / "USER_MANUAL.md").read_text(encoding="utf-8", errors="replace") \
            if (REPO / "docs" / "USER_MANUAL.md").exists() else ""
        agents = (REPO / "AGENTS.md").read_text(encoding="utf-8", errors="replace") \
            if (REPO / "AGENTS.md").exists() else ""
        flags = sorted(o for a in ta.build_parser()._actions for o in a.option_strings
                       if o.startswith("--")) if hasattr(ta, "build_parser") else []
        check("the parser is exposed for doc checks", bool(flags), "no build_parser()")
        missing_m = [f for f in flags if f not in manual]
        missing_a = [f for f in flags if f not in agents]
        check("USER_MANUAL documents every CLI flag", bool(flags) and not missing_m, str(missing_m))
        check("AGENTS.md documents every CLI flag", bool(flags) and not missing_a, str(missing_a))
        # Metadata keys the page embeds must be described for agents and humans.
        for key in ("reported_cost_usd", "reported_cost_partial", "lines_added"):
            check(f"AGENTS.md documents metadata key {key}", key in agents, "missing")
        check("USER_MANUAL explains the reported (cost-state) cost",
              "cost-state" in manual and "reported cost" in manual.lower(), "missing")
        check("AGENTS.md no longer calls cost list-price only",
              "reported" in agents.lower() and "cost-state" in agents, "missing")
        check("README names the reported cost beside the list estimate",
              "reported cost" in readme.lower() or "cost-state" in readme, "missing")
        check("README names cross-archive search as shipped",
              "search" in readme.lower() and "across" in readme.lower()
              and "remaining step" not in readme, "roadmap still lists it")
        # The release commit that lands a README edit is itself one commit,
        # so the stated count may run one ahead of HEAD before it is made.
        n_commits = int(subprocess.run(["git", "rev-list", "--count", "HEAD"], capture_output=True,
                                       text=True, cwd=str(REPO)).stdout.strip() or 0)
        shallow = subprocess.run(["git", "rev-parse", "--is-shallow-repository"], capture_output=True,
                                 text=True, cwd=str(REPO)).stdout.strip() == "true"
        if shallow:
            # CI checks out a single commit; the count is only meaningful on a full clone.
            skip("README's build story counts the commits on main", "shallow checkout")
        else:
            check("README's build story counts the commits on main",
                  any(f"{n} commits" in readme for n in (n_commits, n_commits + 1)),
                  f"HEAD has {n_commits}")
        check("README no longer says 'scribe'", "scribe" not in readme.lower(), "found")
        check("README opening names Markdown among the formats",
              "Markdown" in "\n".join(readme.splitlines()[:14]), "not in opening")
        check("README no longer says 'All four'", "All four" not in readme, "found")
        check("README links the manual and AGENTS.md",
              "USER_MANUAL" in readme and "AGENTS.md" in readme, "links missing")
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8", errors="replace") \
            if (REPO / "CHANGELOG.md").exists() else ""
        check("CHANGELOG names the current version", ta.VERSION in changelog, "version missing")
        # githubify rule 17: the warranty disclaimer and limitation of liability
        # must survive every rewrite -- in LICENSE and, visibly, in the README.
        licence = (REPO / "LICENSE").read_text(encoding="utf-8", errors="replace")
        check("LICENSE disclaims warranty and liability",
              "WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND" in licence and "Limitation of Liability" in licence, "clause missing")
        # githubify rule 17 also asks for the machine-readable licence and an
        # SPDX header in every source file -- both were missing here while the
        # sister repo carried them, found in the project review of 2026-08-29.
        cff = REPO / "CITATION.cff"
        check("CITATION.cff exists", cff.exists(), "missing")
        if cff.exists():
            cff_text = cff.read_text(encoding="utf-8", errors="replace")
            check("CITATION.cff names the Apache licence",
                  "license: Apache-2.0" in cff_text, "licence line missing")
            check("CITATION.cff version matches VERSION",
                  ('version: "%s"' % ta.VERSION) in cff_text,
                  "CITATION.cff is not at %s" % ta.VERSION)
        for rel in ("transcript_archiver.py", "tests/test_archiver.py",
                    "docs/build_manual.py", "examples/make_sample.py",
                    "examples/make_showcase.py"):
            src_text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
            check("%s carries the SPDX header" % rel,
                  "SPDX-License-Identifier: Apache-2.0" in src_text
                  and "Copyright 2026" in src_text, "header missing")
        ci = (REPO / ".github" / "workflows" / "tests.yml").read_text(
            encoding="utf-8", errors="replace")
        check("CI runs pyflakes as well as the suite",
              "pyflakes" in ci, "no static check in CI")
        check("README carries a visible Disclaimer under Licence",
              "### Disclaimer" in readme and "without warrant" in readme
              and "liable" in readme and readme.index("## Licence") < readme.index("### Disclaimer"),
              "disclaimer missing")
    finally:
        shutil.rmtree(tmp2, ignore_errors=True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n[36] The suite leaves the user's real archive untouched")
if _ARCHIVE_BEFORE is None:
    skip("no file appeared in CLAUDE_ARCHIVE_DIR during the suite",
         "CLAUDE_ARCHIVE_DIR unset or missing")
else:
    _new = sorted(_archive_snapshot() - _ARCHIVE_BEFORE)
    check("no file appeared in CLAUDE_ARCHIVE_DIR during the suite", not _new, str(_new[:5]))
_stray = sorted(str(f.relative_to(_SUITE_DEFAULT_ARCHIVE))
                for f in _SUITE_DEFAULT_ARCHIVE.rglob("*") if f.is_file())
check("every check named its --archive-dir (the default archive dir stayed empty)",
      not _stray, str(_stray[:5]))
shutil.rmtree(_SUITE_DEFAULT_ARCHIVE, ignore_errors=True)

print(f"\n{CHECKS[0] - len(FAILURES)}/{CHECKS[0]} checks passed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("ALL GREEN")

# The README states the size of this suite; the number must not drift. Checks
# skipped for a missing TeX count toward the size: they exist, they just did
# not run here.
_readme = (HERE.parent / "README.md").read_text(encoding="utf-8", errors="replace")
_m = re.search(r"(\d+) checks", _readme)
_size = CHECKS[0] + SKIPPED[0]
if not _m or int(_m.group(1)) != _size:
    print(f"FAIL  README states {_m.group(1) if _m else 'no'} checks, suite has "
          f"{_size} ({CHECKS[0]} run + {SKIPPED[0]} skipped)")
    sys.exit(1)
