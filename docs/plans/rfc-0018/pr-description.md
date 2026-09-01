## Summary

Ships **RFC-0018, the admin analyst chat** — a read-only slide-over on every `/admin` tab that answers questions over the business's own numbers (profit and margin, aging stock, consignor position, pricing outliers). It is Phase 3 of the three-phase chat plan, and it lands alongside the still-uncommitted tails of **RFC-0016** (display artifacts), **RFC-0017** (conversation history) and **RFC-0019** (the `/inventory` split workspace).

**The isolation is structural, not a runtime flag.** Admin tools live in a *separate MCP server process* (`python -m merlins_collection.mcp_admin`), so a customer conversation cannot name a tool that reads cost basis — the process serving customers never loaded one. Four things differ between the two surfaces and none of them is an `isAdmin` boolean: the subprocess, the tool contract, the system prompt, and the hydration visibility predicate.

**That server is Python, not the TypeScript workspace the RFC assumed.** `mcp` was already a backend dependency, so this needs no npm workspace, no Dockerfile stage and no CI job — and, far more importantly, its tools import `services/ledger.py` and `services/condition_pricing.py` **directly**. A TypeScript mirror can pin a *value* with a parity test; it cannot pin a *call graph*, and `ledger.py`'s docstring enumerates its readers exhaustively precisely because the failure mode is a reader that forgets to call it.

## Type of Change
- [x] New feature
- [x] Bug fix (four defects found in code this builds on — see Notes)
- [x] Refactor (`lib/conversations.ts` became a factory rather than being copied)
- [x] Config / infra

## TDD Checklist
- [x] RED — failing test written and confirmed failing before implementation
- [x] GREEN — minimal implementation to pass the test
- [x] REFACTOR — code cleaned up, tests still green

Every money property is **mutation-tested**: inverting `split_percent` (it is *our* cut, so the consignor's share is its complement), inlining a second `voided_at is None` check, valuing an unpriced consigned item at `$0`, reporting `0.0` instead of `None` for margin on zero sales, and skipping archived consignors each fail exactly one test and no others.

## Test Plan

| Suite | Result | Baseline |
|---|---|---|
| Backend | **2192 passed** | 2113 |
| Frontend | **1100 passed / 104 files** | 1080 |
| MCP | **101 passed** | 101 |
| Infra | **27 passed** | 27 |
| `ruff check backend/src` | clean | clean |
| `tsc --noEmit` | clean | clean |
| `npm run lint` | 0 errors, 2 pre-existing warnings | same 2 |

Beyond the suites, three things were verified **outside** them, because none is expressible as a unit test:

- **The admin MCP server actually spawns.** `test_admin_mcp_subprocess.py` drives it through the real `McpToolExecutor` and completes a real MCP handshake — everything else in that area imports `build_server` in-process, which proves tools are registered but not that the entry point works.
- **The tool contract actually ships.** Built the wheel, confirmed it contains `merlins_collection/admin-tool-contract.json`, then unpacked it somewhere with no repo checkout in scope and watched the schemas build and the subprocess handshake from that layout.
- **The slide-over was driven in a real browser** at 1440 / 1024 / 768 / 430 / 390 px. Zero console errors, no horizontal overflow, Escape closes the history flyout before the panel, keyboard resize and `localStorage` persistence both work. No chat message was ever sent — that would bill Bedrock and write to the production table.

## Notes

### Four defects found in code this builds on, none of them introduced here

1. **`prune_to_cap` deleted across surfaces.** The 50-thread LRU cap queried every conversation for a `sub` with no surface filter, so the owner using both chats would have had a quarterly margin analysis deleted once their combined thread count passed 50. RFC-0018's own risk table warns "`surface` filter forgotten in one reader" — and the RFC committed that error, on the reader that destroys rows.
2. **Every MCP subprocess inherited the full parent environment.** Under Lambda that handed the *customer* server `ADMIN_API_KEY` and the task role's write credentials, so the process boundary conferred zero privilege isolation. Now an allowlist, so a secret added later is excluded by default rather than by being remembered.
3. **The admin API key was compared with `==`.** A short-circuiting comparison leaks the key one byte at a time to anyone who can time the response — reachable from the public internet, because the backend sits behind a Function URL with `authType: NONE` and no WAF. Now `hmac.compare_digest`.
4. **`mcp-server/src/condition-pricing.ts` claimed its multipliers "are pinned on both sides by tests so a silent divergence fails loudly."** They were not, for the life of the file. Each side had only its own test with independently hardcoded numbers, so re-tuning the Python table would have gone green with TypeScript stale — pricing the same card two ways depending on which half of `/inventory` you were looking at. Two mutation-tested parity tests added; the docstring now names them instead of asserting the property.

### Two guards that could not guard

RFC-0018 never mentions the **30-second Lambda timeout**, which is the binding constraint on the whole feature. Measuring it (`backend/scripts/measure_admin_chat_latency.py`, against the live table, with the customer server as a control) showed the timeout is *not* the problem — no tool on either server exceeds **1.0s**, the worst five-call sequence is **3.6s**, and the admin surface's largest reply is **5× smaller** than the customer chat's unfiltered `search_inventory`. What it exposed instead:

- **`McpToolExecutor`'s per-call timeout was 30.0s — the entire budget.** Its job is to turn one wedged tool into an error string the model narrates around, which needs it to fire with time left to use the result. That error path had never once been reachable in production. Now derived from `LAMBDA_REQUEST_BUDGET_SECONDS`, which a cross-boundary test pins to the CDK stack's actual value.
- **Query-tool calls per request were unbounded.** `_MAX_TOOL_TURNS` bounds round trips to the *model*, not tool calls — one assistant turn may emit any number of `toolUse` blocks. The RED test fed a 40-block turn and **all forty ran**, forty full ten-shard inventory walks in one request. Now capped at 10, with the excess getting a *refusal* rather than an empty result (an empty `toolResult` reads to the model as "the tool found nothing", which is a confident wrong answer on a money question).

Both are pre-existing and both affect the customer chat too.

### Two "passes locally, breaks in production" bugs

- **The admin tool contract was read from `shared/` at request time**, resolved by walking up from `__file__` to the repo root. The Dockerfile never copies `shared/` and installs the package non-editable, so in the image that walk landed on `/usr/local/lib/shared/…` and the first `POST /admin/chat/` would have raised `FileNotFoundError` before Bedrock was ever called — while every test passed, and always would have, because they all run in the one layout where the path is correct. The file now lives inside the package and is read through `importlib.resources`.
- **The analyst chat could not be typed into on any phone.** The dialog was a `position: fixed` descendant of a `backdrop-blur-md` header, and `backdrop-filter` both becomes the containing block for fixed descendants *and* opens a stacking context — so `z-40` resolved inside `z-30`, below the mobile nav's `z-50`, and `document.elementFromPoint` at the composer's centre returned the nav's link. Fixed with `createPortal(…, document.body)`. `getBoundingClientRect` reported the input comfortably inside the viewport the whole time it was unclickable.

### Deliberately not built

- **`stale` / `max_age_days` on `find_pricing_outliers`**, though RFC-0018's tool table lists them: no inventory model carries a per-item price timestamp. `value_note` mentions an age in prose, and parsing a number out of a sentence to drive a money answer is a guess wearing a filter's clothes.
- **An `admin_mcp_command` setting.** `[sys.executable, "-m", "merlins_collection.mcp_admin"]` resolves identically in dev and in the image, so the knob would have no variance to absorb.
- **Voiding a purchase** still has no correction path — unchanged here, recorded because it stays true.

### Deployment

Nothing here needs a new environment variable, image stage or CI job. **Deploy with `bash scripts/deploy-frontend.sh`** (never a bare `cdk deploy`, which drops secrets from the live Lambda) and run `bash scripts/smoke-deployment.sh` afterwards.
