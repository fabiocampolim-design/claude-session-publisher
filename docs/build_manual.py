#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
"""build_manual.py -- render the user manual to HTML and PDF, in every
documentation language.

    python docs/build_manual.py            # English + every translation
    python docs/build_manual.py --stamp    # record the English digest in each

The Markdown is the source of truth; the built files are committed so readers
need no tooling. Uses pandoc for the HTML and pandoc + xelatex for the PDF
when they are on PATH; otherwise falls back to the archiver's own Markdown
renderer for the HTML and says plainly that the PDF was skipped. Never fails
just because a tool is missing.

English is the reference text. Each translation records the digest of the
English it was made from -- `<!-- source-digest: ... -->` in a README, a
`source-digest:` front-matter line in a manual -- and the suite fails when the
English has moved and the translation has not. `--stamp` writes those digests
and is run *after* a translation has been brought up to date, never instead
of doing it.
"""
from __future__ import annotations

import hashlib
import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = HERE / "USER_MANUAL.md"
OUT_HTML, OUT_PDF = HERE / "USER_MANUAL.html", HERE / "USER_MANUAL.pdf"

# The documentation languages besides English: README.<lang>.md and
# docs/USER_MANUAL.<lang>.md, built to USER_MANUAL.<lang>.html / .pdf (2.8.0).
DOC_LANGS = ("pt-BR", "es", "de", "fr")

# The check count is quoted in every document and moves on almost every
# release; it must not, on its own, make every translation look stale.
CHECK_COUNT_RE = re.compile(r"\b(\d{3,4})\s+checks\b|\b(\d{3,4})\s+(?:verificaç|comprobac|Prüf|vérificat)")


def source_digest(text: str) -> str:
    """The digest a translation is stamped with: the English body, with the
    front matter dropped and the check count neutralised, so a release that
    only bumps the number does not mark four translations stale while a real
    change to the English source does."""
    body = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.S)
    body = re.sub(r"\b\d{3,4}\s+checks\b", "N checks", body)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def translation_status(root: Path = ROOT) -> list[dict]:
    """One row per translated document: its path, whether it exists, the
    digest it carries and the digest its English source has now. The suite
    reads this; nothing here writes."""
    want = {"README": source_digest((root / "README.md").read_text(encoding="utf-8")),
            "USER_MANUAL": source_digest((root / "docs" / "USER_MANUAL.md")
                                         .read_text(encoding="utf-8"))}
    rows = []
    for lang in DOC_LANGS:
        for kind, path, pat in (
                ("README", root / f"README.{lang}.md", r"<!-- source-digest: ([0-9a-f]+) -->"),
                ("USER_MANUAL", root / "docs" / f"USER_MANUAL.{lang}.md",
                 r'(?m)^source-digest: "([0-9a-f]*)"')):
            row = {"lang": lang, "kind": kind, "path": path, "exists": path.exists(),
                   "want": want[kind], "have": None}
            if row["exists"]:
                m = re.search(pat, path.read_text(encoding="utf-8"))
                row["have"] = m.group(1) if m else None
            rows.append(row)
    return rows


def stamp_translations(root: Path = ROOT) -> list:
    """Record in every translation the digest of the English text it was made
    from; the suite's staleness check then passes. Run it after a translation
    has been brought up to date, never instead of that. Returns the files that
    carry a digest marker (one without a marker is reported, not silently
    skipped)."""
    done = []
    for row in translation_status(root):
        if not row["exists"]:
            continue
        p, text = row["path"], row["path"].read_text(encoding="utf-8")
        if row["kind"] == "README":
            new, n = re.subn(r"<!-- source-digest: [0-9a-f]* -->",
                             f"<!-- source-digest: {row['want']} -->", text, count=1)
            where = "no <!-- source-digest: ... --> marker in its first lines"
        else:
            new, n = re.subn(r'(?m)^source-digest: "[0-9a-f]*"',
                             f'source-digest: "{row["want"]}"', text, count=1)
            where = "no source-digest line in its front matter"
        if not n:
            print(f"cannot stamp {p.relative_to(root).as_posix()}: {where}")
            continue
        if new != text:
            with open(p, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(new)
        done.append(p.relative_to(root).as_posix())
    return done

CSS = """body{font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif;max-width:860px;
margin:2rem auto;padding:0 1rem;color:#22221f;background:#faf7f0}
h1{font-size:1.6rem;border-bottom:1px solid #999;padding-bottom:.2rem;margin-top:2rem}
h2{font-size:1.25rem;margin-top:1.6rem}table{border-collapse:collapse;width:100%;font-size:.9rem}
th,td{border:1px solid #bbb;padding:.3rem .5rem;text-align:left;vertical-align:top}th{background:#eeebe2}
pre,code{font-family:ui-monospace,Consolas,monospace;font-size:.86rem}pre{background:#eeebe2;padding:.6rem;overflow-x:auto}
@media(prefers-color-scheme:dark){body{color:#e9e6dc;background:#14140f}th,pre{background:#201e17}}"""


def _run(cmd, cwd) -> bool:
    try:
        return subprocess.run(cmd, cwd=str(cwd), capture_output=True,
                              timeout=600).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


_TITLES = {
    "en": "claude-session-publisher — User Manual",
    "pt-BR": "claude-session-publisher — Manual do Usuário",
    "es": "claude-session-publisher — Manual de Usuario",
    "de": "claude-session-publisher — Benutzerhandbuch",
    "fr": "claude-session-publisher — Manuel de l'utilisateur",
}


def _fallback_html(text: str, lang: str = "en") -> str:
    """The archiver's own md_to_html covers everything the manual uses."""
    spec = importlib.util.spec_from_file_location("ta", ROOT / "transcript_archiver.py")
    ta = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ta)
    text = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.S)
    return (f"<!doctype html><html lang=\"{lang}\"><head><meta charset=\"utf-8\">"
            f"<title>{_TITLES.get(lang, _TITLES['en'])}</title>"
            f"<style>{CSS}</style></head><body>{ta.md_to_html(text)}</body></html>")


def build_one(src: Path, out_html: Path, out_pdf: Path, lang: str = "en") -> None:
    """Render one manual -- English or a translation -- to HTML and PDF."""
    text = src.read_text(encoding="utf-8")
    title = _TITLES.get(lang, _TITLES["en"])
    pandoc = shutil.which("pandoc")
    css = HERE / "_manual.css"
    if pandoc:
        css.write_text(CSS, encoding="utf-8")
        ok = _run([pandoc, src.name, "-s", "--toc", "--css", css.name,
                   "--metadata", f"pagetitle={title}", "--metadata", f"lang={lang}",
                   "--embed-resources", "-o", out_html.name], HERE)
        if not ok:   # older pandoc without --embed-resources
            ok = _run([pandoc, src.name, "-s", "--toc", "--css", css.name,
                       "--metadata", f"lang={lang}",
                       "--self-contained", "-o", out_html.name], HERE)
        css.unlink(missing_ok=True)
        if not ok:
            out_html.write_text(_fallback_html(text, lang), encoding="utf-8")
        print(f"wrote {out_html} via {'pandoc' if ok else 'fallback'}")
    else:
        out_html.write_text(_fallback_html(text, lang), encoding="utf-8")
        print(f"wrote {out_html} via fallback (no pandoc)")

    if pandoc and shutil.which("xelatex"):
        ok = _run([pandoc, src.name, "--toc", "--pdf-engine=xelatex",
                   "-V", "geometry:margin=22mm", "-V", "mainfont=DejaVu Serif",
                   "-V", "monofont=DejaVu Sans Mono", "-V", "colorlinks=true",
                   "-V", f"lang={lang}", "-o", out_pdf.name], HERE)
        if not ok:   # fonts by family name may be unknown to fontconfig: retry plain
            ok = _run([pandoc, src.name, "--toc", "--pdf-engine=xelatex",
                       "-V", "geometry:margin=22mm", "-V", "colorlinks=true",
                       "-o", out_pdf.name], HERE)
        print(f"wrote {out_pdf}" if ok else f"PDF build failed for {src.name} "
              "(pandoc + xelatex); the HTML and Markdown are complete")
    else:
        print("PDF skipped: needs pandoc and xelatex on PATH")


def main() -> None:
    if "--stamp" in sys.argv[1:]:
        done = stamp_translations()
        print("stamped: " + (", ".join(done) if done else "nothing"))
        return
    build_one(SRC, OUT_HTML, OUT_PDF, "en")
    for lang in DOC_LANGS:
        src = HERE / f"USER_MANUAL.{lang}.md"
        if src.exists():
            build_one(src, HERE / f"USER_MANUAL.{lang}.html",
                      HERE / f"USER_MANUAL.{lang}.pdf", lang)


if __name__ == "__main__":
    sys.exit(main())
