# 研序（YanXu）前端

React + Vite + Tailwind CSS + Ant Design frontend for the YanXu FastAPI backend.

## Run

```bash
pnpm install
pnpm dev
```

By default the app talks to `http://localhost:8000` and `ws://localhost:8000`.
Override with `.env.local`:

```bash
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_BASE_URL=ws://localhost:8000
```

## Backend Contract

- `POST /api/task`: `{query, thread_id, run_id}`. Generate `run_id` once per submission and reuse it on retries. A different active run in the same thread returns 409; capacity exhaustion returns 429.
- `POST /api/task/{thread_id}/plan`: `{run_id, plan_version, action: "approve" | "revise", feedback}`. Revisions require non-empty feedback. Retry the same version, action and feedback after a lost response; stale decisions return 409. Approval/revision returns 429 without changing the plan if all execution slots are busy.
- `POST /api/task/{thread_id}/cancel?run_id=...`: cancels that run only; repeated cancellation is safe.
- `GET /api/sessions?q=...`: up to 100 recent matching conversations.
- `GET /api/sessions/{thread_id}`: turns, states, timestamps, events, files and uploaded attachment metadata.
- `POST /api/upload`: multipart `thread_id` and `files`; at most 8 files per request, 25 MB each and 100 MB per conversation. Existing names are rejected. Chunked uploads without `Content-Length` are unsupported.
- `GET /api/files?thread_id=...&run_id=...`: generated files for one run and its revision.
- `GET /api/download?thread_id=...&run_id=...&path=...`: relative artifact path from the file list.
- `WebSocket /ws/{thread_id}`: monitor packets carry `thread_id`, `run_id`, `revision` and `event_id`. Answer updates contain a full text snapshot; terminal packets commit the final state.

The hook merges HTTP snapshots and WebSocket packets by run revision. It also reconciles history every five seconds and on window focus. Reloading the page restores the active run, including cancellation controls.

New runs start in `planning`, then `plan_ready` moves them to `waiting_approval`. The plan card supports approval or a new version from feedback. Only `plan_approved` enters `running`; waiting has no active research loader. Cancellation works in all three phases. History includes `plan`, `planVersion`, `usage` and `budget`, so approval survives reloads. Waiting plans reserve their conversation but release the server execution slot.

File-list revisions describe file snapshots only; the hook does not advance the full turn revision from a file-only response, which could otherwise suppress a newer plan/status event.

```bash
pnpm build
```

The backend is a local, single-user service. CORS and ID/path checks do not provide user authentication. See [setup guide](../docs/SETUP.md) for limits and deployment assumptions.
