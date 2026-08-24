"""Generate a synthetic Claude Code session for tests and the README.

Everything here is invented. No real conversation, path, key or name appears.
The session is deliberately built to exercise the paths that broke on real
data during development:

  * a human turn that must survive byte-for-byte, including a pasted block
    whose column alignment must not be re-wrapped
  * assistant markdown: headings, lists, a table, a fenced code block
  * a tool call whose input carries a multi-line file (the pretty-printer)
  * Greek, arrows, box drawing and subscripts (LaTeX transliteration)
  * NUL bytes from UTF-16 output captured byte-wise (halts xelatex if kept)
  * a 3,000-character single line (the hard-wrap path)
  * an empty thinking block, as Claude Code always emits
  * a system record and an unresolved tool call

Run:  python examples/make_sample.py
"""
import datetime
import json
import pathlib

SESSION = "00000000-0000-4000-8000-000000000001"
# Claude Code names a transcript by its session id, and the archiver finds a
# session by matching that filename stem -- so the sample must be named the
# same way, not something friendlier.
OUT = pathlib.Path(__file__).resolve().parent / f"{SESSION}.jsonl"
T0 = datetime.datetime(2026, 1, 15, 9, 0, 0, tzinfo=datetime.timezone.utc)

_n = [0]


def ts(step=17):
    _n[0] += step
    return (T0 + datetime.timedelta(seconds=_n[0])).isoformat().replace("+00:00", "Z")


def uid(i):
    return f"00000000-0000-4000-9000-{i:012d}"


records = []


def add(rec):
    records.append(rec)


add({"type": "ai-title", "aiTitle": "Sample session for tests", "sessionId": SESSION})

BASE = {"sessionId": SESSION, "cwd": "/home/example/project", "version": "2.1.0",
        "userType": "external", "isSidechain": False, "isMeta": False}


def human(i, text):
    add({**BASE, "type": "user", "uuid": uid(i), "timestamp": ts(),
         "promptSource": "typed", "origin": {"kind": "human"},
         "message": {"role": "user", "content": text}})


def assistant(i, blocks, req):
    add({**BASE, "type": "assistant", "uuid": uid(i), "timestamp": ts(),
         "requestId": req,
         "message": {"role": "assistant", "model": "claude-opus-5", "content": blocks,
                     "usage": {"input_tokens": 120, "output_tokens": 340,
                               "cache_read_input_tokens": 5000,
                               "cache_creation": {"ephemeral_5m_input_tokens": 200,
                                                  "ephemeral_1h_input_tokens": 0}}}})


def tool_result(i, tid, content, is_error=False):
    add({**BASE, "type": "user", "uuid": uid(i), "timestamp": ts(),
         "message": {"role": "user",
                     "content": [{"type": "tool_result", "tool_use_id": tid,
                                  "content": content, "is_error": is_error}]}})


# 1 -- a plain question
human(1, "Can you check the lattice constant and plot the band structure?")

assistant(2, [
    {"type": "thinking", "thinking": "", "signature": "synthetic"},
    {"type": "text", "text": (
        "## Plan\n\n"
        "I'll compute the bands, then check the gap. Three things matter here:\n\n"
        "- the broadening Γ = 0.080 eV, not 0.8\n"
        "- the mesh must avoid the high-symmetry points, where the Chern number "
        "is undefined\n"
        "- β and π enter through the hopping phase\n\n"
        "| quantity | value | note |\n"
        "|---|---|---|\n"
        "| lattice constant | 3.61 Å | fcc Cu |\n"
        "| gap | 10⁻⁶ eV | numerically zero |\n\n"
        "```python\n"
        "import numpy as np\n"
        "bands = np.linalg.eigvalsh(H)\n"
        "```\n\n"
        "The arrow → and box drawing ─│┌ appear in tool output below.")},
    {"type": "tool_use", "id": "tool_1", "name": "Write",
     "input": {"file_path": "/home/example/project/bands.py",
               "content": "import numpy as np\n\n"
                          "def bands(H):\n"
                          "    \"\"\"Return sorted eigenvalues.\"\"\"\n"
                          "    return np.linalg.eigvalsh(H)\n"}},
], "req_1")
tool_result(3, "tool_1", "File created successfully at /home/example/project/bands.py")

# 2 -- a pasted block whose alignment must not be re-wrapped
human(4, "here is what it printed, the columns must line up:\n\n"
         "  n     E (eV)    weight\n"
         "  1    -2.4010    0.9987\n"
         "  2    -0.0003    0.5001\n"
         "  3     2.4009    0.9986\n\n"
         "is the middle one a real state?")

assistant(5, [
    {"type": "text", "text": (
        "Yes -- it is the zero mode. Note it sits at 10⁻⁴ eV, not exactly zero, "
        "which is rounding rather than physics.")},
    {"type": "tool_use", "id": "tool_2", "name": "Bash",
     "input": {"command": "python -c 'import numpy; print(numpy.__version__)'",
               "description": "check numpy version"}},
], "req_2")

# tool output with box drawing, a NUL-laden UTF-16 capture, and a very long line
utf16ish = "".join("\x00" + c for c in "Copyright (c) Example Corp")
longline = "x" * 3000
tool_result(6, "tool_2",
            "┌──────┐\n"
            "│ 2.1.0│\n"
            "└──────┘\n"
            + utf16ish + "\n" + longline + "\n→ done ✓")

# 3 -- an error result and an unresolved call
assistant(7, [
    {"type": "text", "text": "One more check, then I'll summarise."},
    {"type": "tool_use", "id": "tool_3", "name": "Bash",
     "input": {"command": "false", "description": "deliberately failing command"}},
], "req_3")
tool_result(8, "tool_3", "command failed with exit code 1", is_error=True)

assistant(9, [
    {"type": "text", "text": "Done. The gap is numerically zero and the zero mode is real."},
    {"type": "tool_use", "id": "tool_4", "name": "Read",
     "input": {"file_path": "/home/example/project/bands.py"}},
], "req_4")
# tool_4 is deliberately left without a result: an interrupted call

# a system record and a harness attachment
add({**BASE, "type": "system", "subtype": "turn_duration", "uuid": uid(10),
     "timestamp": ts(), "durationMs": 41000, "content": "turn complete"})
add({**BASE, "type": "attachment", "uuid": uid(11), "timestamp": ts(),
     "attachmentType": "hook_success", "content": "SessionStart hook ran"})
add({"type": "mode", "sessionId": SESSION, "mode": "default"})
add({"type": "last-prompt", "sessionId": SESSION, "leafUuid": uid(4)})

OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
               encoding="utf-8")
print(f"wrote {OUT} ({len(records)} records)")
