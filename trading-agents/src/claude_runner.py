"""Run a subagent definition (.claude/agents/<name>.md) via headless Claude Code.

Each call is a fresh, tool-less `claude -p` process: the model only returns JSON,
it never touches exchanges. All side effects happen in our Python after the
risk gate. Verify flags against `claude --help` on the VM (they evolve).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from .config import ROOT

AGENTS_DIR = ROOT / ".claude" / "agents"


def _agent_prompt(name: str) -> str:
    text = (AGENTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    return re.sub(r"\A---.*?---\s*", "", text, flags=re.S)  # strip frontmatter


def extract_json(text: str) -> dict:
    """Tolerate code fences / chatter around the JSON object."""
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError(f"no JSON in model output: {text[:200]!r}")
    return json.loads(m.group(0))


async def run_agent(name: str, user_input: dict | str, model: str, timeout: float = 45.0,
                    tools: str = "") -> dict | str:
    payload = user_input if isinstance(user_input, str) else json.dumps(user_input, ensure_ascii=False)
    cmd = [os.getenv("CLAUDE_BIN", "claude"), "-p", payload,
           "--model", model,
           "--append-system-prompt", _agent_prompt(name),
           "--tools", tools,                    # "" = no tools (classification/decision agents)
           "--output-format", "json"]
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(ROOT), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {err.decode()[:300]}")
    envelope = json.loads(out.decode())
    result = envelope.get("result", "")
    return result if tools else extract_json(result)  # tool-using agents (report) return prose
