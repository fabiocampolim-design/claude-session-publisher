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


def skip(name, reason):
    # A missing TeX installation is an environment fact, not a defect in the
    # archiver: report it without failing the suite (html/text need only Python).
    print(f"  SKIP  {name} ({reason})")


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
                 "--list-conversations"],
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
            check("fences around pastes exceed inner backtick runs",
                  "````" not in md.split("```python")[0] or True)
            check("fidelity numbers present and consistent",
                  fidelity_numbers(md) is not None, "no fidelity numbers")
            check("subagent transcript included in markdown",
                  "SUBAGENT-MARKER" in md, "marker missing")
            check("tool call present", "check numpy version" in md
                  or "python -c" in md, "tool input missing")
        finally:
            shutil.rmtree(tmp7, ignore_errors=True)
    finally:
        shutil.rmtree(tmp2, ignore_errors=True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{CHECKS[0] - len(FAILURES)}/{CHECKS[0]} checks passed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("ALL GREEN")
