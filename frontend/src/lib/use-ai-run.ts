"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { AIRun, ConstraintState, Decision } from "./types";
import { api } from "./ui";
import { publicErrorMessage } from "./feedback";

export const terminalStatuses = new Set([
  "completed",
  "needs_clarification",
  "failed",
  "cancelled",
  "interrupted",
]);
export const isActiveRun = (run: AIRun | null) =>
  Boolean(run && !terminalStatuses.has(run.status));

export interface RunRequest {
  message: string;
  mode: "ai" | "algorithmic";
  operation: "generate" | "explain" | "compare" | null;
  current_decisions: Decision[];
  scenario_ids: string[];
  constraints: ConstraintState | null;
}

export function useAIRun() {
  const [run, setRun] = useState<AIRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const activeRequest = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const latestRun = useRef<AIRun | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      controller.current?.abort();
    };
  }, []);

  const watch = useCallback(async (initial: AIRun, signal: AbortSignal) => {
    let next = initial;
    while (!signal.aborted && mounted.current) {
      latestRun.current = next;
      setRun(next);
      if (terminalStatuses.has(next.status)) {
        window.dispatchEvent(new Event("akim-ai-run-completed"));
        break;
      }
      await new Promise<void>((resolve) => {
        const finish = () => {
          signal.removeEventListener("abort", abort);
          resolve();
        };
        const timer = window.setTimeout(finish, 800);
        const abort = () => {
          window.clearTimeout(timer);
          finish();
        };
        signal.addEventListener("abort", abort, { once: true });
      });
      if (signal.aborted) break;
      next = await api<AIRun>(
        `ai/runs/${encodeURIComponent(initial.run_id)}`,
        undefined,
        signal,
      );
    }
  }, []);

  const execute = useCallback(
    async (request: RunRequest) => {
      if (activeRequest.current) return;
      activeRequest.current = true;
      controller.current?.abort();
      const nextController = new AbortController();
      controller.current = nextController;
      setBusy(true);
      setError("");
      setRun(null);
      latestRun.current = null;
      try {
        const initial = await api<AIRun>(
          "ai/runs",
          { ...request, request_id: crypto.randomUUID() },
          nextController.signal,
        );
        await watch(initial, nextController.signal);
      } catch (e) {
        if (!nextController.signal.aborted && mounted.current)
          setError(publicErrorMessage(e));
      } finally {
        if (controller.current === nextController) {
          activeRequest.current = false;
          if (mounted.current) setBusy(false);
        }
      }
    },
    [watch],
  );

  const recover = useCallback(
    async (existing: AIRun) => {
      if (activeRequest.current) return;
      activeRequest.current = true;
      controller.current?.abort();
      const nextController = new AbortController();
      controller.current = nextController;
      setBusy(isActiveRun(existing));
      setError("");
      try {
        await watch(existing, nextController.signal);
      } catch (e) {
        if (!nextController.signal.aborted && mounted.current)
          setError(publicErrorMessage(e));
      } finally {
        if (controller.current === nextController) {
          activeRequest.current = false;
          if (mounted.current) setBusy(false);
        }
      }
    },
    [watch],
  );

  const cancel = useCallback(async () => {
    const current = latestRun.current;
    if (!current || terminalStatuses.has(current.status)) return;
    controller.current?.abort();
    setError("");
    try {
      const cancelled = await api<AIRun>(
        `ai/runs/${encodeURIComponent(current.run_id)}/cancel`,
        {},
      );
      if (mounted.current) {
        setRun(cancelled);
        latestRun.current = cancelled;
      }
    } catch (e) {
      if (mounted.current) setError(publicErrorMessage(e));
    } finally {
      activeRequest.current = false;
      if (mounted.current) setBusy(false);
    }
  }, []);

  return { run, busy, error, execute, recover, cancel };
}
