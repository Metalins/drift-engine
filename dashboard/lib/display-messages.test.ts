/**
 * Unit tests for the #31 presentation dictionary.
 *
 * Runs on Node's built-in test runner with native TypeScript support
 * (Node >= 22.18) — no extra dependency. Excluded from the Next/tsc build
 * include (see tsconfig "exclude") because it imports the module under test
 * with an explicit `.ts` extension for the Node runtime.
 *
 *   node --test lib/display-messages.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  ATTENTION_DISPLAY,
  BEHAVIORAL_STATUS_DISPLAY,
  CRYPTO_STATUS_DISPLAY,
  WATCHER_STATE_DISPLAY,
  displayAttention,
  displayBehavioralStatus,
  displayCryptoStatus,
  displayWatcherState,
  humanizeCode,
} from "./display-messages.ts";

test("humanizeCode turns any raw snake_case code into readable prose", () => {
  assert.equal(humanizeCode("challenges_expired"), "Challenges expired");
  assert.equal(humanizeCode("mcp_not_responding"), "Mcp not responding");
  assert.equal(humanizeCode("some-new-kebab-code"), "Some new kebab code");
  assert.equal(humanizeCode(""), "");
});

test("no mapped label contains raw snake_case jargon", () => {
  const everyLabel = [
    ...Object.values(CRYPTO_STATUS_DISPLAY),
    ...Object.values(BEHAVIORAL_STATUS_DISPLAY),
    ...Object.values(WATCHER_STATE_DISPLAY),
    ...Object.values(ATTENTION_DISPLAY),
  ];
  for (const label of everyLabel) {
    assert.ok(label.length > 0, "label must not be empty");
    // A snake_case identifier is lowercase words joined by underscores.
    assert.ok(
      !/[a-z]+_[a-z]+/.test(label),
      `label still contains code-like jargon: "${label}"`,
    );
  }
});

test("displayAttention prefers a backend message when present", () => {
  assert.equal(
    displayAttention("challenges_expired", "Custom backend copy."),
    "Custom backend copy.",
  );
  // Blank / whitespace-only messages fall back to the dictionary.
  assert.equal(
    displayAttention("challenges_expired", "   "),
    ATTENTION_DISPLAY.challenges_expired,
  );
  assert.equal(
    displayAttention("challenges_expired", null),
    ATTENTION_DISPLAY.challenges_expired,
  );
});

test("displayAttention never returns a raw code for unknown inputs", () => {
  const out = displayAttention("totally_unknown_code");
  assert.equal(out, "Totally unknown code");
  assert.ok(!out.includes("_"));
});

test("known status codes resolve to their human labels", () => {
  assert.equal(displayCryptoStatus("verified"), "Verified");
  assert.equal(displayCryptoStatus("action_required"), "Not trusted");
  assert.equal(displayBehavioralStatus("not_enough_data"), "Learning your baseline");
  assert.equal(displayWatcherState("error"), "Needs attention");
  assert.equal(displayWatcherState("active"), "Connected");
});
