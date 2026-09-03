/**
 * RFC 0025 T2/T3 — the sticker-price visibility rule, pinned on both sides.
 *
 * `isPublicInventory` (dynamodb-repository.ts) is a TypeScript mirror of
 * Python's `is_customer_visible` (services/customer_visibility.py) — a
 * SECURITY boundary, per that module's own docstring: leaking sold/held or
 * bulk/sealed stock, or now a stickerless card, is the failure mode. Both
 * sides load the SAME shared fixture and assert independently — see
 * backend/tests/test_cross_boundary.py's `test_customer_visibility_matches_shared_cases`
 * for the other half, and CLAUDE.md's standing warning that this file has
 * claimed cross-language parity before that no test actually checked.
 */
import { readFileSync } from "node:fs";
import { describe, it, expect } from "vitest";
import { isPublicInventory } from "../dynamodb-repository.js";

interface CustomerVisibilityCase {
  name: string;
  status: string;
  kind: string;
  location: string | null;
  factory_sealed: boolean;
  sticker_price: string | null;
  expected: boolean;
}

function loadCases(): CustomerVisibilityCase[] {
  const raw = readFileSync(
    new URL("../../../shared/test-fixtures/customer-visibility-cases.json", import.meta.url),
    "utf-8",
  );
  return JSON.parse(raw).cases;
}

describe("isPublicInventory matches the shared cross-boundary fixture", () => {
  const cases = loadCases();

  it("the fixture has not lost cases", () => {
    expect(cases.length).toBeGreaterThanOrEqual(8);
  });

  for (const c of cases) {
    it(`case: ${c.name}`, () => {
      const row = {
        status: c.status,
        kind: c.kind,
        location: c.location,
        factory_sealed: c.factory_sealed,
        sticker_price: c.sticker_price,
      };
      expect(isPublicInventory(row)).toBe(c.expected);
    });
  }
});
