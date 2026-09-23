import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { api } from "../src/lib/ui.ts";
import { actionUnavailable, serviceUnavailable } from "../src/lib/feedback.ts";

const originalFetch = globalThis.fetch;
const invalidScenario = {
  valid: false,
  errors: [{ code: "BUDGET_EXCEEDED", message: "Budget exceeds 100" }],
};

afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("scenario validation errors remain structured and never acquire a score", async () => {
  globalThis.fetch = async () =>
    Response.json(invalidScenario, { status: 422 });
  const result = await api("scenario/preview", { decisions: [] });
  assert.deepEqual(result, invalidScenario);
  assert.equal("score" in result, false);
});

test("a structured server failure is not misinterpreted as a simulation", async () => {
  globalThis.fetch = async () =>
    Response.json(invalidScenario, { status: 500 });
  await assert.rejects(api("scenario/simulate", { decisions: [] }));
});

test("advisor validation failure cannot become an invalid Advisor object", async () => {
  globalThis.fetch = async () =>
    Response.json(invalidScenario, { status: 422 });
  await assert.rejects(api("ai/explain", { decisions: [] }));
});

test("dataset failures reject rather than reaching the dashboard as arrays", async () => {
  globalThis.fetch = async () =>
    Response.json(invalidScenario, { status: 422 });
  await assert.rejects(api("districts"));
});

test("non-JSON upstream failure is safe for the UI", async () => {
  globalThis.fetch = async () =>
    new Response("<html>Proxy error</html>", { status: 502 });
  await assert.rejects(api("base-state"), { name: "Error" });
});

test("server diagnostics cannot leak through the API error message", async () => {
  globalThis.fetch = async () =>
    Response.json(
      {
        error: {
          code: "UNGROUNDED_EXPLANATION",
          message: "A.critical_after[0].value private details",
        },
      },
      { status: 500 },
    );
  await assert.rejects(api("base-state"), { message: serviceUnavailable });
});

test("browser network exceptions become a neutral message", async () => {
  globalThis.fetch = async () => {
    throw new TypeError("fetch failed at private-internal-host");
  };
  await assert.rejects(api("base-state"), { message: actionUnavailable });
});

test("a malformed successful response rejects safely before reaching components", async () => {
  globalThis.fetch = async () =>
    new Response("private proxy diagnostics", { status: 200 });
  await assert.rejects(api("base-state"), { message: serviceUnavailable });
});
