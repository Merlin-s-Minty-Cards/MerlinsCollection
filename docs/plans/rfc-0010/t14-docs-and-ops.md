# T14 — Docs stop describing a PSA integration that will never exist

**RFC:** 0010 §H · **Layer:** docs/ops · **Depends on: T12** · **Blocks:** T-FINAL

No behaviour changes here. The job is that a reader six months from now finds a **decision** where
PSA used to be, not a half-explained gap — and that CLAUDE.md matches the twelve fixes that just
landed.

## Why this is a real task and not a chore

CLAUDE.md is loaded into every session's context. Right now it tells the next agent that PSA is
*pending approval* and that the two disabled buttons are *placeholders on purpose*. Both were true
on 2026-08-09 and are false now. A stale instruction file does not just mislead — it actively
directs work at something the owner has cancelled.

RFC 0009's own T8 hit this and had to correct **five** wrong claims in its task doc before it could
execute. Expect to find similar drift.

## Files

- `CLAUDE.md` — "Third-Party APIs", "Admin Panel" (the Slabs paragraph), "Site Pages" if needed
- `backend/.env.example` — remove `PSA_API_KEY`
- `docs/rfcs/0009-slab-intake-and-graded-pricing.md` — amendment banner
- `docs/plans/rfc-0009/progress.md` — T2/T5 rows, and the PSA row in the Blocked table
- `docs/plans/rfc-0009/README.md` — the T2/T5 table rows and the "Do not" list
- `docs/plans/rfc-0009/t2-psa-lookup-and-quota.md`, `t5-camera-scan.md` — banners
- `docs/plans/rfc-0009/spike-findings.md` — a closing note on §1.5
- `docs/aws-setup.md` — Phase 8's key-rotation procedure (PSA half)
- `README.md` if it mentions PSA
- `docs/plans/rfc-0010/progress.md` — mark T14 done
- **Tests:** `backend/tests/test_config.py`

## The changes

### 1. `PSA_API_KEY` out of `backend/.env.example`

It is read by **no code** — there is no `psa_api_key` field on `Settings` and
`model_config`'s `extra="ignore"` swallows the env var entirely. So this is a documentation
removal with **zero behavioural change**, and
`test_config.py::test_there_is_still_no_psa_setting_to_configure` already guards that the field
never appears.

**Update that test's docstring**, which currently frames the absence as *"the field belongs with
the client that reads it (T2)"*. T2 is now WON'T DO, so the honest reason is *"there is no PSA
client and there will not be one"*. The assertion is unchanged; the reason it exists is not.

Do **not** remove the test. It is now a permanent tripwire rather than a temporary one.

### 2. RFC 0009 T2 and T5 → WON'T DO

In `progress.md`, `README.md` and each task doc. State plainly:

> **WON'T DO (2026-08-10).** PSA's cert API became a **paid** feature and the owner declined it.
> This was previously `DEFERRED` pending free-tier account approval; that approval is no longer
> being sought. See RFC 0010 §H. **Do not email `collectors-apis@collectors.com`** and do not
> retry the endpoint — every attempt costs quota and cannot succeed.

Keep the 403 evidence, the key fingerprint and the Swagger findings. They are the record of *why*
this was investigated properly rather than abandoned on a guess, and deleting them would make the
decision look casual.

The `psa_403_not_approved.json` fixture stays. It documents an outcome.

### 3. CLAUDE.md

The **"Third-Party APIs"** section's PSA paragraph currently opens *"PSA cert API — has NEVER been
called successfully. Do not build on it"* and ends *"When approval lands, PSA returns as a
pre-fill."* Rewrite the ending: **approval is not coming.** Keep the "never call it" instruction —
it is still the right instruction, now for a permanent reason.

The **"Slabs"** paragraph in the Admin Panel section says the intake toolbar *"has four buttons,
and two of them are deliberately dead"* and describes "Scan cert" as a real affordance. After T12
there are **no** PSA buttons and **no** Scan cert button. Rewrite it, and keep the load-bearing
part:

> `CertInput` still advances on Enter and strips trailing `\r\n`, which is what makes a
> keyboard-wedge scanner work in the ordinary cert field. There is no scanner UI because none is
> needed — a wedge scanner is a fast keyboard. **Do not remove that handling.**

Also add, in the same paragraph, that a slab is priced **after** commit via a scoped
`refresh-prices`, never inside the commit loop, and that an unmatched slab is unpriceable by
construction.

**And record the twelve Round 8 fixes** where they change a documented behaviour. At minimum:

| CLAUDE.md claim to update | because |
|---|---|
| Triage's reason list and filter behaviour | T3 — reasons now come from the server, one `triage_reason` param, no sticker reason |
| Prep Queue's description | T7 — sorts and filters by location |
| the money-input convention | T0/T1 — `parseMoney`, never `parseFloat`, never `type="number"` on money |
| the transaction ledger | T10/T11 — `batch_id` and the void fields, plus the ONE countability predicate |
| the admin sidebar order table | T13 — grouped; the table should show groups |
| `Consignor` write semantics | T2 — `put_consignor` now sweeps, like `put_show` |

**Add a "Never" line for each trap this RFC found**, in the same voice as the existing ones — those
lines are the highest-value thing in the file:

- *"Never use `parseFloat` on money. `parseFloat("1,300")` is **1**, and it is not `NaN`, so it
  passes every `isNaN` guard in the codebase."*
- *"Never pass a date-only string to `new Date()`. It parses as UTC midnight and renders a day
  early in every US timezone."*
- *"Never let an aggregate inline its own voided-transaction check. One predicate,
  `services/ledger.is_countable`."*

### 4. `docs/aws-setup.md`

Phase 8's rotation procedure covers both keys. The PSA half is now moot — the pricing key is the
only one that matters. Note that rather than deleting the section, since **rotating the pricing key
is still outstanding** from RFC 0009 T8 and the procedure is needed.

### 5. Leak sweep

Before committing, confirm no API key value is in the diff. RFC 0009's T-FINAL fixed its own
self-matching grep; reuse the corrected form (excludes `docs/plans/`, greps for the value shape as
well as the variable name), and note that this task is *removing* key references, which is the safe
direction.

## RED — an honest exception

**There is no RED phase, and that is stated rather than faked.** This task changes prose, a
template and comments — no behaviour — so nothing can fail first. Inventing a failing test for a
docstring produces a fake RED and a test that asserts prose.

CLAUDE.md's gate binds **behavioural** change. RFC 0009 T8 made exactly this call on 2026-08-09
and recorded it; follow that precedent and record it again in `progress.md`.

What this task *does* do is update `test_config.py`'s existing docstring and re-run it, plus the
three RFC 0009 documentation guards that assert the credit arithmetic. If a doc guard fails, a
number in the docs is wrong — fix the doc, not the test.

```bash
./.venv/Scripts/python.exe -m pytest backend/tests/test_config.py -q --tb=short
```

## GREEN — done when

- `test_config.py` passes (2 pre-existing + the RFC 0009 doc guards).
- `grep -ri "psa" CLAUDE.md docs/ backend/.env.example README.md` returns only text that describes
  PSA as **withdrawn**, plus the historical evidence in RFC 0009's spike findings.
- `grep -rn "PSA_API_KEY" .` returns nothing outside RFC 0009's historical docs.
- The app still boots with the pricing key forced empty and `build_pricing_provider()` returns
  `None` — unchanged behaviour, worth confirming since you edited `.env.example`.
- `ruff check backend/src` clean.

## Do not

- Do not delete RFC 0009's T2/T5 docs, its PSA evidence, or the `psa_403_not_approved.json`
  fixture. Mark them; do not erase them.
- Do not remove `test_config.py::test_there_is_still_no_psa_setting_to_configure`. It is now
  permanent.
- Do not add `PSA_DAILY_QUOTA` or any PSA setting.
- Do not delete `docs/aws-setup.md` Phase 8 — the pricing key still needs rotating.
- Do not fake a RED phase.
- Do not leave CLAUDE.md describing the four-button toolbar or "approval pending". That file is
  loaded into every session and a stale instruction actively directs work at cancelled scope.

---

## Done means: committed, recorded, and the next prompt emitted

This task is finished when **all five** of these are true. Four is not done.

1. **The narrow test selection above passes**, and you have shown the output. Not "should pass".
2. **[`progress.md`](progress.md) is updated** — this row set to `DONE` with the commit sha, a
   Notes line if a later task needs to know something, and anything surprising added to the
   Decisions table.
3. **Out-of-scope findings are appended to [`follow-ups.md`](follow-ups.md)** — not fixed as a
   side errand, and not left only in the conversation.
4. **The work is committed.** One focused commit, or a small series, in this branch's
   conventional-commit style (`feat(scope):` / `fix(scope):` / `docs(scope):`). Do not merge, do
   not push unless asked.
5. **Your final output is the ready-to-paste prompt below**, so a fresh conversation can pick up
   the next task without the owner reconstructing anything.

### Next in the chain

**T-FINAL — Full verification and the PR**

End your reply with exactly this, in a copyable block:

```
Read docs/plans/rfc-0010/progress.md and docs/plans/rfc-0010/t-final-verification.md.

Execute that task only, following the RED gate in the doc: write the failing
tests first, show me the failing output, and wait for my confirmation before
implementing. Do not start any other task.

When it is done: update progress.md and follow-ups.md, commit the work, and end
your reply with a ready-to-paste prompt for the next task in the chain.
```
