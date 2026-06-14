/**
 * Unit tests for the gh-98 legacy-domain redirect.
 *
 * Excluded from the Next/tsc build (tsconfig "exclude": **\/*.test.ts) and
 * run under Node's built-in test runner:
 *
 *   node --test lib/legacy-domain.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";

import { legacyDomainRedirect } from "./legacy-domain.ts";

test("redirects the apex metalins.ai host to metalins.com, preserving path", () => {
  assert.equal(legacyDomainRedirect("metalins.ai", "/"), "https://metalins.com/");
  assert.equal(
    legacyDomainRedirect("metalins.ai", "/docs"),
    "https://metalins.com/docs",
  );
  assert.equal(
    legacyDomainRedirect("metalins.ai", "/v/my-bot?ref=tg"),
    "https://metalins.com/v/my-bot?ref=tg",
  );
});

test("redirects the www.metalins.ai variant too", () => {
  assert.equal(
    legacyDomainRedirect("www.metalins.ai", "/products"),
    "https://metalins.com/products",
  );
});

test("is case-insensitive and ignores a :port suffix", () => {
  assert.equal(
    legacyDomainRedirect("Metalins.AI:443", "/docs"),
    "https://metalins.com/docs",
  );
});

test("never redirects the API host (api.metalins.ai stays put)", () => {
  assert.equal(legacyDomainRedirect("api.metalins.ai", "/v1/verify-proof"), null);
});

test("does not redirect the canonical metalins.com host", () => {
  assert.equal(legacyDomainRedirect("metalins.com", "/"), null);
  assert.equal(legacyDomainRedirect("www.metalins.com", "/docs"), null);
});

test("does not redirect the workers.dev preview host (used by QA)", () => {
  assert.equal(
    legacyDomainRedirect(
      "metalins-dashboard.josemiguelhernandez-es.workers.dev",
      "/",
    ),
    null,
  );
});

test("returns null for a missing host header", () => {
  assert.equal(legacyDomainRedirect(null, "/"), null);
  assert.equal(legacyDomainRedirect(undefined, "/"), null);
  assert.equal(legacyDomainRedirect("", "/"), null);
});

test("normalizes a path that arrives without a leading slash", () => {
  assert.equal(
    legacyDomainRedirect("metalins.ai", "docs"),
    "https://metalins.com/docs",
  );
});
