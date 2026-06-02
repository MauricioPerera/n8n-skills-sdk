#!/usr/bin/env python3
"""
agent_harness.py — does a local model build an n8n workflow with THIS stack
(llms.txt skill + @n8n/workflow-sdk + REST, NO MCP) as well as it did with the
25-tool MCP?

Companion to ../skills llms/llms-txt-skills/evals/poc_orchestration. That POC
measured the MCP arms (skill: 8 tools, 6 calls; dispatch: 1 tool; rest: 1 tool).
Here the capability is delivered as a published SKILL.md + 3 local tools backed
by the SDK (parse/validate, local) and the REST API (create) — no MCP server.

The 3 tools are executed by shelling out to the REAL CLI (src/n8n-skill.mjs),
i.e. exactly what a real agent following the skill would run.

Tools (vs the MCP's 25):
  reference(section)  -> n8n-skill reference   (= get_sdk_reference)
  validate(code)      -> n8n-skill validate    (= validate_workflow, local)
  create(code)        -> n8n-skill create       (= create_workflow_from_code)

Metrics per task: success, tool_calls, errors, turns, validate_attempts.

Usage:
  set N8N_API_KEY=...    (REST key; create needs it)
  python agent_harness.py --model-id qwen/qwen3.5-9b [--task schedule-slack] [--verbose]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
LM_BASE = os.environ.get("LM_BASE_URL", "http://localhost:1234/v1")
API_BASE = os.environ.get("N8N_API_BASE", "https://ardf.dev/api/v1")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
MAX_TURNS = 14
TOOL_RESULT_CAP = 4000
SKILL = (HERE / "skills" / "build-n8n-workflow" / "SKILL.md").read_text(encoding="utf-8")

TASKS = [
    {"id": "schedule-slack",
     "task": "Create an n8n workflow that runs on a schedule (every day at 9am) and sends a message to Slack saying 'Daily standup time'. Build and create it. Leave it as a draft."},
    {"id": "webhook-http",
     "task": "Create an n8n workflow with a Webhook trigger that, when called, makes an HTTP GET request to https://api.example.com/status. Build and create it. Leave it as a draft."},
    {"id": "schedule-http-set",
     "task": "Create an n8n workflow that runs every hour, calls https://api.example.com/metrics via HTTP, and uses a Set node to keep only the field 'value'. Build and create it. Leave it as a draft."},
]

TOOLS = [
    {"type": "function", "function": {
        "name": "reference",
        "description": "Get the @n8n/workflow-sdk reference (patterns/rules/expressions/functions).",
        "parameters": {"type": "object", "properties": {
            "section": {"type": "string", "enum": ["patterns", "rules", "expressions", "functions"]}},
            "required": ["section"]}}},
    {"type": "function", "function": {
        "name": "search_nodes",
        "description": "Find which n8n node to use for a need (SDK node-selection guidance).",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "node_types",
        "description": "Get exact parameters for node types (comma-separated). Optional; if unavailable, write from reference and rely on validate.",
        "parameters": {"type": "object", "properties": {
            "types": {"type": "string", "description": "e.g. scheduleTrigger,slack"}}, "required": ["types"]}}},
    {"type": "function", "function": {
        "name": "validate",
        "description": "Validate @n8n/workflow-sdk code locally. Returns {valid, errors, warnings}.",
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string", "description": "SDK code, NO import line"}}, "required": ["code"]}}},
    {"type": "function", "function": {
        "name": "create",
        "description": "Parse + validate + create the workflow via REST. Returns {created, id}.",
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string", "description": "SDK code, NO import line"}}, "required": ["code"]}}},
]

SYS = (
    "You build n8n workflows WITHOUT the n8n MCP, using three local tools backed "
    "by @n8n/workflow-sdk and the REST API. Follow the published skill.\n\n"
    "--- SKILL: build-n8n-workflow ---\n" + SKILL +
    "\n\nTools: `reference`, `search_nodes`, `node_types` (optional helpers), then "
    "`validate` and `create`. Minimal path is reference -> validate -> create; use "
    "search_nodes/node_types only for unfamiliar nodes. When done, reply with the id."
)


# ---- LM Studio chat + reasoning-channel tool-call recovery (from poc_harness) ----
class ContextOverflow(Exception):
    pass


def chat(model, messages):
    payload = json.dumps({"model": model, "messages": messages, "tools": TOOLS,
                          "temperature": 0, "max_tokens": 1200}).encode()
    req = urllib.request.Request(LM_BASE.rstrip("/") + "/chat/completions", data=payload,
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer lm-studio"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if "context length" in body or "n_ctx" in body or "n_keep" in body:
            raise ContextOverflow(body[:200])
        raise RuntimeError(f"LM Studio {e.code}: {body[:200]}")


_TC = [0]


def _recover_calls(text):
    out = []
    if not text:
        return out
    for fm in re.finditer(r"<function=([A-Za-z0-9_]+)>(.*?)</function>", text, re.DOTALL):
        args = {}
        for pm in re.finditer(r"<parameter=([A-Za-z0-9_]+)>\s*(.*?)\s*</parameter>", fm.group(2), re.DOTALL):
            raw = pm.group(2).strip()
            try:
                args[pm.group(1)] = json.loads(raw)
            except Exception:
                args[pm.group(1)] = raw
        _TC[0] += 1
        out.append({"id": f"s{_TC[0]}", "type": "function",
                    "function": {"name": fm.group(1), "arguments": json.dumps(args)}})
    return out


# ---- tool executor: shell out to the REAL CLI ----
def run_cli(args, code=None):
    return subprocess.run(["node", "src/n8n-skill.mjs", *args], cwd=str(HERE),
                          input=code, capture_output=True, text=True, timeout=120)


def exec_tool(name, args, metrics):
    if name == "reference":
        r = run_cli(["reference", args.get("section", "patterns")])
        return r.stdout[:TOOL_RESULT_CAP] or "[no output]", False
    if name == "search_nodes":
        r = run_cli(["search-nodes", args.get("query", "")])
        return r.stdout[:TOOL_RESULT_CAP] or "[no output]", False
    if name == "node_types":
        r = run_cli(["node-types", args.get("types", "")])
        return r.stdout[:TOOL_RESULT_CAP] or "[no output]", False
    if name == "validate":
        metrics["validate_attempts"] += 1
        r = run_cli(["validate"], code=args.get("code", ""))
        try:
            j = json.loads(r.stdout)
            return r.stdout, not j.get("valid", False)
        except Exception:
            return (r.stdout or r.stderr)[:TOOL_RESULT_CAP], True
    if name == "create":
        r = run_cli(["create"], code=args.get("code", ""))
        try:
            j = json.loads(r.stdout)
        except Exception:
            return (r.stdout or r.stderr)[:TOOL_RESULT_CAP], True
        if j.get("created") and j.get("id"):
            metrics["created_ids"].append(j["id"])
            metrics["success"] = True
            return r.stdout, False
        return r.stdout, True
    return f"[unknown tool {name}]", True


def run_one(model, task, verbose):
    messages = [{"role": "system", "content": SYS}, {"role": "user", "content": task["task"]}]
    m = {"tool_calls": 0, "errors": 0, "turns": 0, "validate_attempts": 0,
         "created_ids": [], "success": False, "seq": [], "fatal": None}
    t0 = time.time()
    for _ in range(MAX_TURNS):
        m["turns"] += 1
        try:
            resp = chat(model, messages)
        except ContextOverflow as e:
            m["fatal"] = "context_overflow"; m["turns"] -= 1; break
        except Exception as e:
            m["fatal"] = f"{type(e).__name__}: {e}"; break
        msg = resp["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            calls = _recover_calls((msg.get("reasoning_content") or "") + "\n" + (msg.get("content") or ""))
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        if not calls:
            break
        for tc in calls:
            fn = tc["function"]["name"]
            m["tool_calls"] += 1
            m["seq"].append(fn)
            try:
                a = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                result, err = "[bad JSON args]", True
            else:
                result, err = exec_tool(fn, a, m)
            if err:
                m["errors"] += 1
            if verbose:
                print(f"    -> {fn} {'ERR' if err else 'ok'}: {result[:110].replace(chr(10),' ')}")
            messages.append({"role": "tool", "tool_call_id": tc.get("id", fn), "content": result[:TOOL_RESULT_CAP]})
        if m["success"]:
            break
    m["wall_s"] = round(time.time() - t0, 1)
    return m


def cleanup(ids):
    key = os.environ.get("N8N_API_KEY")
    for wid in ids:
        try:
            req = urllib.request.Request(f"{API_BASE}/workflows/{wid}", method="DELETE",
                                         headers={"X-N8N-API-KEY": key, "User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                print(f"  [cleanup] deleted {wid} (HTTP {r.status})")
        except Exception as e:
            print(f"  [cleanup] could not delete {wid}: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-id", required=True)
    ap.add_argument("--task")
    ap.add_argument("--no-cleanup", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--out", default=str(HERE / "agent-results.json"))
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not os.environ.get("N8N_API_KEY"):
        print("ERROR: set N8N_API_KEY (REST key) — create needs it."); return 2

    tasks = [t for t in TASKS if t["id"] == args.task] if args.task else TASKS
    print(f"stack: skill + @n8n/workflow-sdk + REST (NO MCP) | 3 tools | model={args.model_id}")
    rows, created = [], []
    for t in tasks:
        print(f"\n=== task={t['id']} (sdk-rest, no MCP) ===")
        m = run_one(args.model_id, t, args.verbose)
        created += m["created_ids"]
        rows.append({"task": t["id"], **m})
        fatal = f" FATAL={m['fatal']}" if m["fatal"] else ""
        print(f"  success={m['success']} tool_calls={m['tool_calls']} errors={m['errors']} "
              f"turns={m['turns']} validate_attempts={m['validate_attempts']} wall_s={m['wall_s']}{fatal}")
        print(f"  seq: {' -> '.join(m['seq']) or '(none)'}")

    n = len(rows)
    if n:
        print("\n" + "=" * 60)
        print(f"{'n':>3} {'success%':>9} {'avg_calls':>10} {'avg_errors':>11} {'avg_turns':>10}")
        print(f"{n:>3} {sum(r['success'] for r in rows)/n*100:>8.0f}% "
              f"{sum(r['tool_calls'] for r in rows)/n:>10.1f} {sum(r['errors'] for r in rows)/n:>11.1f} "
              f"{sum(r['turns'] for r in rows)/n:>10.1f}")
    Path(args.out).write_text(json.dumps({"model": args.model_id, "stack": "skill+sdk+rest", "rows": rows},
                                         indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {args.out}")
    if created and not args.no_cleanup:
        print(f"\nCleaning up {len(created)} workflow(s)...")
        cleanup(created)
    return 0


if __name__ == "__main__":
    sys.exit(main())
