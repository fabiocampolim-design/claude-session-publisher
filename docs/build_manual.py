#!/usr/bin/env python3
"""build_manual.py -- render docs/USER_MANUAL.md to USER_MANUAL.html and .pdf.

    python docs/build_manual.py

The Markdown is the source of truth; the built files are committed so readers
need no tooling. Uses pandoc for the HTML and pandoc + xelatex for the PDF
when they are on PATH; otherwise falls back to the archiver's own Markdown
renderer for the HTML and says plainly that the PDF was skipped. Never fails
just because a tool is missing.
"""
from __future__ import annotations

import html
import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "USER_MANUAL.md"
OUT_HTML, OUT_PDF = HERE / "USER_MANUAL.html", HERE / "USER_MANUAL.pdf"

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


def _fallback_html(text: str) -> str:
    """The archiver's own md_to_html covers everything the manual uses."""
    spec = importlib.util.spec_from_file_location("ta", HERE.parent / "transcript_archiver.py")
    ta = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ta)
    text = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.S)
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<title>claude-session-publisher — User Manual</title>"
            f"<style>{CSS}</style></head><body>{ta.md_to_html(text)}</body></html>")


def main() -> None:
    text = SRC.read_text(encoding="utf-8")
    pandoc = shutil.which("pandoc")
    css = HERE / "_manual.css"
    used = []
    if pandoc:
        css.write_text(CSS, encoding="utf-8")
        ok = _run([pandoc, SRC.name, "-s", "--toc", "--css", css.name,
                   "--metadata", "pagetitle=claude-session-publisher — User Manual",
                   "--embed-resources", "-o", OUT_HTML.name], HERE)
        if not ok:   # older pandoc without --embed-resources
            ok = _run([pandoc, SRC.name, "-s", "--toc", "--css", css.name,
                       "--self-contained", "-o", OUT_HTML.name], HERE)
        css.unlink(missing_ok=True)
        used.append("pandoc" if ok else "fallback")
        if not ok:
            OUT_HTML.write_text(_fallback_html(text), encoding="utf-8")
    else:
        OUT_HTML.write_text(_fallback_html(text), encoding="utf-8")
        used.append("fallback (no pandoc)")
    print(f"wrote {OUT_HTML} via {used[-1]}")

    if pandoc and shutil.which("xelatex"):
        ok = _run([pandoc, SRC.name, "--toc", "--pdf-engine=xelatex",
                   "-V", "geometry:margin=22mm", "-V", "mainfont=DejaVu Serif",
                   "-V", "monofont=DejaVu Sans Mono", "-V", "colorlinks=true",
                   "-o", OUT_PDF.name], HERE)
        if not ok:   # fonts by family name may be unknown to fontconfig: retry plain
            ok = _run([pandoc, SRC.name, "--toc", "--pdf-engine=xelatex",
                       "-V", "geometry:margin=22mm", "-V", "colorlinks=true",
                       "-o", OUT_PDF.name], HERE)
        print(f"wrote {OUT_PDF}" if ok else "PDF build failed (pandoc + xelatex); "
              "the HTML and Markdown are complete")
    else:
        print("PDF skipped: needs pandoc and xelatex on PATH")


if __name__ == "__main__":
    sys.exit(main())
