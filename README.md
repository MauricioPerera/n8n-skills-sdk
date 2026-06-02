# n8n-skills-sdk

**Experiment:** reproduce the n8n MCP server's "build a workflow" capability
using only an **llms.txt-published Skill** + the **[`@n8n/workflow-sdk`](https://www.npmjs.com/package/@n8n/workflow-sdk)**
package + the **n8n REST API** — with **no MCP**, and a handful of generic CLI
tools in context instead of the MCP's 25 (the capability knowledge lives in the
skill prose + the SDK, not in tool schemas).

Companion to the [llms.txt Skills RFC](https://github.com/MauricioPerera/llms-txt-skills)
(`evals/poc_orchestration/`): that POC measured the 25→1 tool-in-context spectrum
against the live n8n MCP. This project takes the last rung — *no MCP at all* — and
shows the MCP is, in essence, a thin server wrapper around a local SDK + the REST API.

## The insight

The n8n MCP exposes **25 tools** to build a workflow. But its core operations are
just the `@n8n/workflow-sdk` package plus one REST call:

| n8n MCP tool | reproduced here by |
|---|---|
| `get_sdk_reference` | `@n8n/workflow-sdk/prompts/sdk-reference` → `n8n-skill reference` |
| `search_nodes` / `get_suggested_nodes` | the SDK's `prompts/node-selection` → `n8n-skill search-nodes` |
| `get_node_types` | `n8n-skill node-types` — exact params **when a `nodes.json` is configured**; otherwise the local `validate` loop reports parameter errors (the benchmark showed this suffices for common nodes) |
| `validate_workflow` | `validateWorkflow()` from the SDK — **runs locally** → `n8n-skill validate` |
| `create_workflow_from_code` | `parseWorkflowCode()` (local) + `POST /api/v1/workflows` (REST) → `n8n-skill create` |

All five n8n MCP build tools now have a local/REST equivalent.

### Enabling exact `node-types`

`node-types` returns exact per-node parameters from a `nodes.json` — the
descriptions array n8n itself ships (pre-generated) at
`<pkg>/dist/types/nodes.json` in every node package. Build one from any local
n8n's node modules (e.g. the npx cache left by `npx n8n`):

```bash
# point at a node_modules dir that has n8n-nodes-base + @n8n/n8n-nodes-langchain
node scripts/build-nodes-json.mjs "<…/_npx/<hash>/node_modules>" nodes.json
# -> merges + prefixes 600+ node descriptions into nodes.json (gitignored, ~9 MB)
```

Then `node-types scheduleTrigger,slack` returns the real `properties` and
`version`s. Set `N8N_NODES_JSON=path` to point elsewhere. **Version note:** the
params track the n8n version of that source — match it to your target instance
for exact fidelity (close minor versions are fine for common nodes; the verified
build here used n8n 2.23.2 against a 2.18.x instance).

Without a `nodes.json`, `node-types` degrades gracefully and agents write from
`reference` and let `validate` catch parameter mistakes — which the
[benchmark](#benchmark-this-stack-vs-the-mcp-agentic-same-local-model) showed is
enough for common workflows.

So an agent never loads 25 tool definitions. It reads **one published skill**
([`skills/build-n8n-workflow/SKILL.md`](skills/build-n8n-workflow/SKILL.md)) that
carries the recipe, and calls **one CLI primitive** (`src/n8n-skill.mjs`).

## What works (verified live against an n8n instance)

```
$ N8N_API_KEY=... node demo.mjs
1. parse SDK code -> workflow JSON (local, = create_workflow_from_code's parse)
   nodes: Schedule -> Slack
2. validate locally (= validate_workflow)
   valid: true errors: 0 warnings: 0
3. create via REST POST /workflows (= create_workflow_from_code's save)
   created id: SBU4EazUj4BBCCUq
4. cleanup: DELETE /workflows/SBU4EazUj4BBCCUq
   delete HTTP 200

Reproduced the MCP's build->validate->create path with 0 MCP tools.
```

## Benchmark: this stack vs. the MCP (agentic, same local model)

`agent_harness.py` drives a local model (`qwen/qwen3.5-9b` via LM Studio) through
a real loop, building workflows with **this stack** — the published skill + 5
local tools (`reference`/`search_nodes`/`node_types`/`validate`/`create`) that
shell out to the real CLI. No MCP. Compared against the MCP arms from the RFC POC
(same model, same `schedule-slack` task):

| stack | MCP? | tools in context | avg tool calls | validation | success |
|---|:---:|---:|---:|:---:|:---:|
| MCP, raw (`naive`/`n8n`) | yes | 25 | 6–7 | yes | (does **not fit** a 4k-context model) |
| MCP, skill + segment | yes | 8 | 6 | yes | ✅ |
| MCP, 1 passthrough (`dispatch`) | yes | 1 | 7 | yes | ✅ |
| MCP, REST-only (`rest`) | no | 1 | 1 | **no** (skipped) | ✅ |
| **skill + @n8n/workflow-sdk + REST** | **no** | **5** | **2.3** | **yes** | **✅ 3/3** |

This stack (N=3: `schedule-slack`, `webhook-http`, `schedule-http-set`) hit
**100% success at avg 2.3 tool calls, 0 errors, every workflow valid on the first
`validate`** — the agent takes the minimal `validate → create` path (sometimes
preceded by `reference`). The five tools include `search_nodes`/`node_types` (the
`get_node_types` equivalent), but on these common nodes the agent **used neither**
— the SDK reference + skill carry the node knowledge, so it writes correct code in
one shot. And unlike the MCP `rest` arm, it **keeps local validation** (the SDK's
`validateWorkflow`). Five tool definitions, no server.

Run it: `N8N_API_KEY=... python agent_harness.py --model-id qwen/qwen3.5-9b`
(raw rows in `agent-results.json`). MCP numbers are N=1 from the POC; this is N=3,
single model — a proof, not a benchmark.

### Across models

| model | size | result on `schedule-slack` |
|---|---|---|
| `qwen/qwen3.5-9b` | 9B | ✅ 3/3 tasks, avg 2.3 calls (`validate → create`, ± `reference`) |
| `ibm/granite-3.2-8b` | 8B | ✅ 3 calls — confirms it's not qwen-specific |
| `mistralai/ministral-3-3b` | 3B | ✗ looped on `reference`, never wrote code |

Two capable ~8–9B models complete it cleanly in ~3 calls. A 3B model hits a
**capability floor** — it can follow the tool protocol but can't *write* the SDK
code. That floor is about the model, not the stack: the MCP path needs the same
code-writing ability, and on a small-context model the MCP's 25 tools don't even
fit (RFC POC, Finding 0). The skill+SDK+REST stack at least *runs* on small
context (5 small tool defs); whether it *succeeds* is gated by the model's coding skill.
Raw rows: `agent-results-granite.json`, `agent-results-ministral.json`.

## Use

```bash
npm install                                   # installs @n8n/workflow-sdk

node src/n8n-skill.mjs reference patterns      # = get_sdk_reference
node src/n8n-skill.mjs search-nodes slack      # = search_nodes / get_suggested_nodes
node src/n8n-skill.mjs node-types scheduleTrigger,slack   # = get_node_types (needs nodes.json)
printf '%s' "$CODE" | node src/n8n-skill.mjs validate     # = validate_workflow (local)
N8N_API_KEY=... printf '%s' "$CODE" | node src/n8n-skill.mjs create   # = create_workflow_from_code

N8N_API_KEY=... node demo.mjs                  # full end-to-end proof (self-cleaning)
```

Config:
- `N8N_API_BASE` — default `https://ardf.dev/api/v1`
- `N8N_API_KEY` — n8n REST API key (`X-N8N-API-KEY`), for `create`. **Never commit it.**
- `N8N_NODES_JSON` — path to a `nodes.json` for exact `node-types` (default `nodes.json`; see above).

## How this maps to the agent flow

An agent pointed at this instance reads `/llms.txt` → finds the `## Skills`
entry → fetches the `SKILL.md` (verifiable via the inline `sha256`) → follows the
recipe: write SDK code, `validate`, `create`. The whole "capability" lives as
**prose + one CLI**, discovered on demand, instead of 25 eagerly-loaded MCP tools.

## Honest caveats

- **Version coupling.** SDK + node `typeVersion`s track the n8n version (here the
  SDK is `@n8n/workflow-sdk@0.15.3`; the target instance is n8n 2.18.x). A skill
  that embeds node shapes is more version-coupled than a live MCP — the trade-off
  for dropping the server. `reference` mitigates this by sourcing the SDK's own docs.
- **Scope.** This reproduces the build→validate→create path (the MCP's center of
  gravity), not every one of the 25 tools (executions, data tables, etc.).
- It is an experiment / proof, not a production tool.
