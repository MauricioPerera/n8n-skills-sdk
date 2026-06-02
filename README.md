# n8n-skills-sdk

**Experiment:** reproduce the n8n MCP server's "build a workflow" capability
using only an **llms.txt-published Skill** + the **[`@n8n/workflow-sdk`](https://www.npmjs.com/package/@n8n/workflow-sdk)**
package + the **n8n REST API** — with **no MCP** and **zero tool schemas** loaded
into the agent's context.

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
| `search_nodes` / `get_suggested_nodes` | the SDK's `prompts/node-selection` + `node-recommendations` (+ the skill's node list) |
| `validate_workflow` | `validateWorkflow()` from the SDK — **runs locally** |
| `create_workflow_from_code` | `parseWorkflowCode()` (local) + `POST /api/v1/workflows` (REST) |

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

## Use

```bash
npm install                                  # installs @n8n/workflow-sdk

node src/n8n-skill.mjs reference patterns     # = get_sdk_reference
printf '%s' "$CODE" | node src/n8n-skill.mjs validate   # = validate_workflow (local)
N8N_API_KEY=... printf '%s' "$CODE" | node src/n8n-skill.mjs create   # = create_workflow_from_code

N8N_API_KEY=... node demo.mjs                 # full end-to-end proof (self-cleaning)
```

Config:
- `N8N_API_BASE` — default `https://ardf.dev/api/v1`
- `N8N_API_KEY` — n8n REST API key (`X-N8N-API-KEY`). **Never commit it.**

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
