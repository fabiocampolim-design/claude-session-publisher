# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
"""Generate the showcase conversation: a small, invented session built to
demonstrate every feature on one page.

Everything here is fictional -- no real conversation, person, path or key.
The story: hunting a zero-energy edge state in a graphene nanoribbon. It
carries, deliberately:

  * P/R reference tags across two models, a failing tool call and a retry
  * markdown with headings, a table, code, and a list that switches marker
  * Greek, sub/superscripts, box drawing, an emoji and a bra-ket the TeX
    fonts cannot set (so the drop-accounting has something to count)
  * a pasted columnar block that must never be re-wrapped
  * a pasted image, a hook attachment, a background-task notification
  * a subagent transcript (tagged A1.*), linked from the Agent call
  * a context compaction, an unresolved tool call, and one corrupt line

Run:  python examples/make_showcase.py
Then: python transcript_archiver.py 0000c0de-cafe-4000-8000-00000000f00d \
          --projects-root examples --archive-dir demo --format html,pdf
"""
import datetime
import json
import pathlib

SESSION = "0000c0de-cafe-4000-8000-00000000f00d"
AGENT_ID = "0000000000000c0d"
OUT = pathlib.Path(__file__).resolve().parent / f"{SESSION}.jsonl"
T0 = datetime.datetime(2026, 4, 1, 9, 0, 0, tzinfo=datetime.timezone.utc)
_n = [0]

# a 1x1 red PNG -- the smallest honest "pasted image"
RED_DOT = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
           "2mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def ts(step=23):
    _n[0] += step
    return (T0 + datetime.timedelta(seconds=_n[0])).isoformat().replace("+00:00", "Z")


def uid(i):
    return f"0000c0de-0000-4000-9000-{i:012d}"


records = []
BASE = {"sessionId": SESSION, "cwd": "/home/ada/ribbon", "version": "2.1.0",
        "userType": "external", "isSidechain": False, "isMeta": False}


def add(rec):
    records.append(rec)


def human(i, text):
    add({**BASE, "type": "user", "uuid": uid(i), "timestamp": ts(),
         "promptSource": "typed", "origin": {"kind": "human"},
         "message": {"role": "user", "content": text}})


def assistant(i, blocks, req, model="claude-opus-5", out_tokens=420):
    add({**BASE, "type": "assistant", "uuid": uid(i), "timestamp": ts(),
         "requestId": req,
         "message": {"role": "assistant", "model": model, "content": blocks,
                     "usage": {"input_tokens": 210, "output_tokens": out_tokens,
                               "cache_read_input_tokens": 18000,
                               "cache_creation": {"ephemeral_5m_input_tokens": 900,
                                                  "ephemeral_1h_input_tokens": 350}}}})


def tool_result(i, tid, content, is_error=False, extra=None):
    add({**BASE, "type": "user", "uuid": uid(i), "timestamp": ts(),
         **(extra or {}),
         "message": {"role": "user",
                     "content": [{"type": "tool_result", "tool_use_id": tid,
                                  "content": content, "is_error": is_error}]}})


add({"type": "ai-title", "aiTitle": "Zero-mode hunt in a graphene ribbon",
     "sessionId": SESSION})
add({**BASE, "type": "attachment", "uuid": uid(1), "timestamp": ts(),
     "attachment": {"type": "hook_success", "hookName": "SessionStart",
                    "exitCode": 0, "stdout": "conda env 'ribbon' activated"}})

# ---- P1 -------------------------------------------------------------------
human(2, "I think our zigzag ribbon has a zero mode we're not resolving. "
         "Can you check the spectrum near E = 0 and tell me whether it's a "
         "real edge state or numerical noise?")

assistant(3, [
    {"type": "thinking", "thinking": "", "signature": "synthetic"},
    {"type": "text", "text": (
        "## Plan\n\n"
        "A zigzag ribbon should carry a flat band at E = 0 from the edge "
        "states. Three things to pin down:\n\n"
        "1. build the tight-binding ribbon and diagonalise\n"
        "2. check how the near-zero eigenvalue scales with width\n"
        "- the broadening Γ = 0.080 eV must not smear the gap\n"
        "- k-mesh must avoid the K points, where the winding is undefined\n\n"
        "| quantity | value | note |\n"
        "|---|---|---|\n"
        "| hopping t | 2.7 eV | standard graphene |\n"
        "| width | 24 sites | zigzag |\n"
        "| target gap | < 10⁻⁶ eV | numerically zero |\n\n"
        "```python\n"
        "import numpy as np\n"
        "E = np.linalg.eigvalsh(H(k))\n"
        "```")},
    {"type": "tool_use", "id": "sc_t1", "name": "Write",
     "input": {"file_path": "/home/ada/ribbon/zigzag.py",
               "content": "import numpy as np\n\n"
                          "def H(k, width=24, t=2.7):\n"
                          "    \"\"\"Zigzag-ribbon Bloch Hamiltonian.\"\"\"\n"
                          "    h = np.zeros((width, width))\n"
                          "    # ... hoppings ...\n"
                          "    return h\n"}},
], "sc_req_1")
tool_result(4, "sc_t1", "File created successfully at /home/ada/ribbon/zigzag.py")

assistant(5, [
    {"type": "text", "text": "Running the diagonalisation on a 400-point k line."},
    {"type": "tool_use", "id": "sc_t2", "name": "Bash",
     "input": {"command": "python zigzag.py --kpoints 400",
               "description": "diagonalise the ribbon"}},
], "sc_req_2", model="claude-sonnet-5", out_tokens=160)
tool_result(6, "sc_t2",
            "┌──────────┬──────────┐\n"
            "│  k/π     │  E₀ (eV) │\n"
            "├──────────┼──────────┤\n"
            "│  0.667   │  2.1e-07 │\n"
            "│  0.750   │  3.4e-09 │\n"
            "│  0.833   │  1.1e-11 │\n"
            "└──────────┴──────────┘\n"
            "flat band found in 2π/3 < |k| < π  → done ✓")

# ---- P2: a paste whose columns must survive -------------------------------
human(7, "here's what the cluster printed overnight, the columns must line up:\n\n"
         "  n     E (eV)       IPR      edge weight\n"
         "  11   -0.004210    0.021    0.11\n"
         "  12   -0.000003    0.489    0.97\n"
         "  13    0.000002    0.492    0.98\n"
         "  14    0.004195    0.020    0.12\n\n"
         "which pair is the edge state?")

assistant(8, [
    {"type": "text", "text": (
        "States 12 and 13 — inverse participation ratio near 0.5 and edge "
        "weight ≈ 1 mean each lives on one edge. Let me confirm the "
        "localisation length on the big lattice.")},
    {"type": "tool_use", "id": "sc_t3", "name": "Bash",
     "input": {"command": "python localization.py --lattice 4096",
               "description": "localisation length on the full lattice"}},
], "sc_req_3")
tool_result(9, "sc_t3",
            "Traceback (most recent call last):\n"
            "  File \"localization.py\", line 44, in <module>\n"
            "    psi = np.linalg.eigh(H_full)\n"
            "MemoryError: Unable to allocate 128. GiB for array",
            is_error=True)

assistant(10, [
    {"type": "text", "text": "Dense diagonalisation won't fit — switching to "
                             "shift-invert around E = 0, which needs only the "
                             "six states we care about."},
    {"type": "tool_use", "id": "sc_t4", "name": "Bash",
     "input": {"command": "python localization.py --lattice 4096 --sigma 0 --k 6",
               "description": "sparse shift-invert near E=0"}},
], "sc_req_4")
tool_result(11, "sc_t4",
            "6 eigenpairs converged in 3.1 s\n"
            "localisation length xi = 1.9 a  (edge state, decays into the bulk)")

# ---- subagent: independent verification -----------------------------------
assistant(12, [
    {"type": "text", "text": "Before I call it, a subagent will verify the "
                             "protection argument independently."},
    {"type": "tool_use", "id": "sc_t5", "name": "Agent",
     "input": {"description": "Verify zero-mode protection",
               "prompt": "Check whether the zigzag edge state at E=0 is "
                         "protected by chiral symmetry.",
               "subagent_type": "general-purpose"}},
], "sc_req_5")
tool_result(13, "sc_t5", "Async agent launched (running in the background).",
            extra={"toolUseResult": {"isAsync": True,
                                     "status": "async_launched",
                                     "agentId": AGENT_ID}})

add({**BASE, "type": "user", "uuid": uid(14), "timestamp": ts(),
     "origin": {"kind": "task-notification"},
     "message": {"role": "user", "content":
                 "<task-notification>\n<task-id>" + AGENT_ID + "</task-id>\n"
                 "<status>completed</status>\n"
                 "<summary>Verification finished: chiral symmetry present, "
                 "zero mode protected.</summary>\n</task-notification>"}})

# ---- P3: a pasted image ---------------------------------------------------
human(15, "sketch of the geometry attached — does the sublattice colouring "
          "match your convention?")
add({**BASE, "type": "user", "uuid": uid(16), "timestamp": ts(),
     "promptSource": "typed", "origin": {"kind": "human"},
     "message": {"role": "user",
                 "content": [{"type": "image",
                              "source": {"type": "base64",
                                         "media_type": "image/png",
                                         "data": RED_DOT}}]}})

assistant(17, [
    {"type": "text", "text": (
        "Yes — A sublattice on the top edge, B on the bottom, matching the "
        "calculation.\n\n"
        "**Verdict:** the pair at ±3 μeV is a genuine chiral-symmetry-protected "
        "edge mode, not noise: it scales like e^(−width/ξ) with ξ = 1.9 a, the "
        "subagent's independent check agrees, and ⟨ψ₁₂|ψ₁₃⟩ ≈ 0 as the two "
        "edges decouple. Ship it ✓")},
    {"type": "tool_use", "id": "sc_t6", "name": "Read",
     "input": {"file_path": "/home/ada/ribbon/results/summary.txt"}},
], "sc_req_6")
# sc_t6 deliberately unresolved: the archive snapshot caught it mid-flight

add({**BASE, "type": "system", "subtype": "compact_boundary", "uuid": uid(18),
     "timestamp": ts(), "content": "",
     "compactMetadata": {"trigger": "auto", "preTokens": 143000,
                         "postTokens": 21000, "cumulativeDroppedTokens": 122000}})
add({**BASE, "type": "system", "subtype": "turn_duration", "uuid": uid(19),
     "timestamp": ts(), "durationMs": 428000, "content": "turn complete"})
add({"type": "mode", "sessionId": SESSION, "mode": "default"})
for leaf, text in ((2, "I think our zigzag ribbon has a zero mode we're not "
                       "resolving. Can you check the spectrum near E = 0 and "
                       "tell me whether it's a real edge state or numerical "
                       "noise?"),
                   (7, "here's what the cluster printed overnight, the columns "
                       "must line up:"),
                   (15, "sketch of the geometry attached — does the sublattice "
                        "colouring match your convention?")):
    add({"type": "last-prompt", "sessionId": SESSION, "leafUuid": uid(leaf),
         "lastPrompt": text})

lines = [json.dumps(r, ensure_ascii=False) for r in records]
# a transcript truncated mid-write: the fidelity report counts it
lines.append('{"type": "assistant", "uuid": "the power went out right about h')
OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"wrote {OUT} ({len(records)} records + 1 corrupt line)")

# ---- the subagent's own conversation --------------------------------------
AGENT_BASE = {**BASE, "isSidechain": True, "agentId": AGENT_ID}
agent_records = [
    {**AGENT_BASE, "type": "user", "uuid": uid(101), "timestamp": ts(),
     "message": {"role": "user",
                 "content": "Check whether the zigzag edge state at E=0 is "
                            "protected by chiral symmetry."}},
    {**AGENT_BASE, "type": "assistant", "uuid": uid(102), "timestamp": ts(),
     "requestId": "sc_agent_req_1",
     "message": {"role": "assistant", "model": "claude-sonnet-5",
                 "content": [
                     {"type": "text", "text":
                      "The zigzag Hamiltonian is bipartite: with Σ = diag(+1 on "
                      "A, −1 on B), ΣHΣ = −H. Any state at E pairs with one at "
                      "−E, so a *single* state at E = 0 cannot move without "
                      "breaking the symmetry. Verifying numerically:"},
                     {"type": "tool_use", "id": "sc_a1", "name": "Bash",
                      "input": {"command": "python -c \"import check; "
                                           "check.chiral('/home/ada/ribbon')\"",
                                "description": "verify anticommutation"}},
                 ],
                 "usage": {"input_tokens": 95, "output_tokens": 610,
                           "cache_read_input_tokens": 4000,
                           "cache_creation": {"ephemeral_5m_input_tokens": 60,
                                              "ephemeral_1h_input_tokens": 0}}}},
    {**AGENT_BASE, "type": "user", "uuid": uid(103), "timestamp": ts(),
     "message": {"role": "user",
                 "content": [{"type": "tool_result", "tool_use_id": "sc_a1",
                              "content": "‖{Σ,H}‖ = 3.2e-16  → chiral symmetry "
                                         "PRESENT (machine precision)",
                              "is_error": False}]}},
    {**AGENT_BASE, "type": "assistant", "uuid": uid(104), "timestamp": ts(),
     "requestId": "sc_agent_req_2",
     "message": {"role": "assistant", "model": "claude-sonnet-5",
                 "content": [{"type": "text", "text":
                              "Confirmed: the anticommutator vanishes to "
                              "machine precision, so the E = 0 pair is "
                              "symmetry-protected. Reporting back."}],
                 "usage": {"input_tokens": 95, "output_tokens": 130,
                           "cache_read_input_tokens": 4200,
                           "cache_creation": {"ephemeral_5m_input_tokens": 20,
                                              "ephemeral_1h_input_tokens": 0}}}},
]
AGENT_DIR = OUT.parent / SESSION / "subagents"
AGENT_DIR.mkdir(parents=True, exist_ok=True)
AGENT_OUT = AGENT_DIR / f"agent-{AGENT_ID}.jsonl"
AGENT_OUT.write_text(
    "\n".join(json.dumps(r, ensure_ascii=False) for r in agent_records) + "\n",
    encoding="utf-8")
print(f"wrote {AGENT_OUT} ({len(agent_records)} records)")
