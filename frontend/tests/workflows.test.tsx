import { beforeEach, describe, expect, test, vi } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Dashboard from "@/components/dashboard";
import { ResultsModal } from "@/components/results";
import type {
  AIRun,
  AISession,
  ConstraintState,
  District,
  Measure,
  SavedScenario,
  SimulationResult,
} from "@/lib/types";
import model from "./fixtures/model.json";

vi.mock("@/components/charts", () => ({
  DistrictRadar: () => <div aria-label="Радар районов" />,
  ComparisonChart: () => <div aria-label="График сравнения" />,
}));

const fixture = model as unknown as {
  districts: District[];
  measures: Measure[];
  base: SimulationResult;
  previewM7: SimulationResult;
  a: SimulationResult;
  b: SimulationResult;
};
const constraints: ConstraintState = {
  max_budget: 100,
  reserve_budget: 0,
  excluded_measure_ids: ["M3"],
  locked_decisions: [],
  focus_district: "Нура",
  preferred_categories: [],
  allowed_districts: null,
  requested_scenario_count: 3,
  analysis_indicators: ["S1", "S2"],
};
const metadata = {
  provider: "openai",
  requested_model: "gpt-4.1-mini",
  actual_model: "gpt-4.1-mini",
  used_llm: true,
  fallback_used: false,
  cache_hit: false,
  api_calls: 2,
  usage: { input_tokens: 200, output_tokens: 90, cached_input_tokens: 20 },
  usage_unknown: false,
  estimated_cost_usd: 0.000224,
};
const narrative = {
  summary: "Варианты проверены по правилам модели.",
  observations: ["Улучшены социальные показатели."],
  remaining_issues: [],
  tradeoffs: ["Резерв бюджета ограничен."],
  limitations: ["Условные данные, не прогноз."],
  evidence_refs: ["scenario_a.score.after"],
  scenario_ids: ["scenario-a", "scenario-b"],
  source: "openai" as const,
};
const initialRows: SavedScenario[] = [fixture.a, fixture.b].map(
  (result, i) => ({
    scenario_id: `scenario-${i ? "b" : "a"}`,
    name: `Сценарий ${i ? "B" : "A"}`,
    decisions: result.decisions,
    result,
    provenance: "llm_generated",
    constraints,
    dataset_version: "test-v1",
    saved: false,
    created_at: "2026-09-23T09:00:00Z",
  }),
);

let requests: {
  path: string;
  body: Record<string, unknown> | undefined;
  headers: HeadersInit | undefined;
}[];
let saved: SavedScenario[];
let failAI: boolean;
let remainRunning: boolean;
let currentConstraints: ConstraintState;
let history: AISession["history"];
let restoredRuns: AIRun[];

function run(
  status: AIRun["status"] = "completed",
  operation?: unknown,
): AIRun {
  return {
    run_id: `run-${Math.max(1, requests.filter((request) => request.path === "ai/runs").length)}`,
    status,
    stage: status,
    message:
      status === "failed"
        ? "Провайдер отклонил запрос."
        : status === "completed"
          ? "Проверено два разных варианта в пределах лимита."
          : "Операция выполняется.",
    error:
      status === "failed"
        ? {
            code: "QUOTA_EXCEEDED",
            message:
              "Квота провайдера исчерпана. Ручной режим остаётся доступен.",
          }
        : null,
    constraints: currentConstraints,
    scenarios:
      status === "completed" &&
      operation !== "compare" &&
      operation !== "explain"
        ? initialRows
        : [],
    explanation: status === "completed" ? narrative : null,
    metadata,
    events: [
      { stage: "interpreting", message: "Ограничения разобраны." },
      { stage: "validating", message: "Два варианта прошли проверку." },
    ],
    clarification: null,
  };
}

beforeEach(() => {
  localStorage.setItem("akim-ai.session", "test-session");
  requests = [];
  saved = [];
  failAI = false;
  remainRunning = false;
  currentConstraints = { ...constraints };
  history = [];
  restoredRuns = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).replace("/api/", "");
      const body = init?.body
        ? (JSON.parse(String(init.body)) as Record<string, unknown>)
        : undefined;
      requests.push({ path, body, headers: init?.headers });
      const respond = (value: unknown, status = 200) =>
        Response.json(value, { status });
      if (path === "districts") return respond(fixture.districts);
      if (path === "measures") return respond(fixture.measures);
      if (path === "base-state") return respond(fixture.base);
      if (path === "sessions/current")
        return respond({
          session_id: "test-session",
          constraints: currentConstraints,
          history,
          runs: restoredRuns,
        });
      if (path === "ai/config")
        return respond({
          enabled: true,
          provider: "openai",
          model: "gpt-4.1-mini",
          key_configured: true,
          allow_template_fallback: false,
          limits: {},
        });
      if (path === "ai/usage")
        return respond({
          day: "2026-09-23",
          estimated_cost_usd: 0,
          api_calls: 0,
          reserved_cost_usd: 0,
          usage_unknown: false,
          daily_limit_usd: 2,
          input_tokens: 0,
          output_tokens: 0,
          cached_input_tokens: 0,
        });
      if (path === "scenario/preview")
        return respond(
          (body?.decisions as unknown[]).length === 1
            ? fixture.previewM7
            : fixture.a,
        );
      if (path === "scenario/simulate") return respond(fixture.a);
      if (path === "ai/runs" && body) {
        history.push({ role: "user", content: String(body.message) });
        if (String(body.message).includes("20")) {
          currentConstraints = { ...currentConstraints, reserve_budget: 20 };
          history.push({
            role: "assistant",
            content:
              "Уточните, какую меру нужно перенести. Резерв и остальные ограничения сохранены.",
          });
          return respond(
            {
              ...run("needs_clarification"),
              clarification: "Какую меру нужно перенести?",
            },
            202,
          );
        }
        return respond(
          run(
            failAI ? "failed" : body.operation ? "completed" : "queued",
            body.operation,
          ),
          202,
        );
      }
      if (path === "ai/runs/run-1")
        return respond(run(remainRunning ? "generating" : "completed"));
      if (path === "ai/runs/run-1/cancel") return respond(run("cancelled"));
      if (path === "scenarios?saved_only=true") return respond(saved);
      if (path === "scenarios/manual-scenario/export") return respond(saved[0]);
      if (path.endsWith("/save")) {
        const id = path.split("/")[1];
        const row = {
          ...(initialRows.find((s) => s.scenario_id === id) || initialRows[0]),
          saved: true,
        };
        saved = [
          ...saved.filter((s) => s.scenario_id !== row.scenario_id),
          row,
        ];
        return respond(row);
      }
      if (path === "scenarios" && body) {
        const row: SavedScenario = {
          ...initialRows[0],
          scenario_id: "manual-scenario",
          name: String(body.name),
          provenance: body.provenance as SavedScenario["provenance"],
          saved: Boolean(body.saved),
        };
        if (row.saved) saved = [...saved, row];
        return respond(row);
      }
      if (path === "scenarios/compare")
        return respond({
          scenarios: initialRows,
          category_comparison: Object.keys(fixture.a.category_deltas).map(
            (category) => ({
              category,
              scenario_a:
                fixture.a.category_deltas[
                  category as keyof typeof fixture.a.category_deltas
                ],
              scenario_b:
                fixture.b.category_deltas[
                  category as keyof typeof fixture.b.category_deltas
                ],
            }),
          ),
        });
      throw new Error(`Unexpected mocked API request: ${path}`);
    }),
  );
});

async function openDashboard() {
  const user = userEvent.setup();
  render(<Dashboard />);
  await screen.findByRole("heading", { name: "Районы города" });
  await waitFor(() =>
    expect(requests.some((r) => r.path === "ai/config")).toBe(true),
  );
  return user;
}

async function generate() {
  const user = await openDashboard();
  await user.click(
    screen.getAllByRole("button", {
      name: "Лаборатория сценариев",
    })[0],
  );
  await user.type(
    screen.getByLabelText("Ваш запрос или уточнение"),
    "Покажи до трёх вариантов, без M3, с анализом школ Нуры.",
  );
  await user.click(screen.getByRole("button", { name: "Отправить запрос" }));
  await screen.findByRole(
    "heading",
    { name: "Проверенные варианты" },
    { timeout: 5000 },
  );
  const cards = screen
    .getAllByRole("heading", { name: /^Сценарий [AB]$/ })
    .map((heading) => heading.closest("article")!);
  return { user, cards };
}

describe("connected city workflows with a mocked backend", () => {
  test("nested laboratory reports portal outside hidden app content and print explicitly", async () => {
    const user = userEvent.setup();
    const print = vi.spyOn(window, "print").mockImplementation(() => {});
    const mountedReport = render(
      <div className="app-content">
        <section hidden>
          <ResultsModal
            result={fixture.a}
            measures={fixture.measures}
            onClose={() => {}}
          />
        </section>
      </div>,
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Будущее города в цифрах",
    });
    expect(dialog.closest(".app-content")).toBeNull();
    expect(dialog.closest(".modal-backdrop")?.parentElement).toBe(
      document.body,
    );
    expect(dialog).toBeVisible();
    expect(document.body.style.overflow).toBe("hidden");
    await user.click(
      within(dialog).getByRole("button", { name: "Печатный отчёт" }),
    );
    expect(print).toHaveBeenCalledOnce();
    expect(
      requests.filter((request) => request.path === "ai/runs"),
    ).toHaveLength(0);
    mountedReport.unmount();
    expect(document.body.style.overflow).not.toBe("hidden");
  });
  test("changing a mounted report cannot explain the old saved scenario", async () => {
    const user = userEvent.setup();
    const report = render(
      <ResultsModal
        result={fixture.a}
        measures={fixture.measures}
        onClose={() => {}}
      />,
    );
    await user.click(
      screen.getByRole("button", { name: "Объяснить с помощью ИИ" }),
    );
    await waitFor(() =>
      expect(requests.filter((r) => r.path === "ai/runs")).toHaveLength(1),
    );
    report.rerender(
      <ResultsModal
        result={fixture.b}
        measures={fixture.measures}
        onClose={() => {}}
      />,
    );
    await user.click(
      screen.getByRole("button", { name: "Объяснить с помощью ИИ" }),
    );
    await waitFor(() =>
      expect(requests.filter((r) => r.path === "scenarios")).toHaveLength(2),
    );
    expect(
      requests.filter((r) => r.path === "scenarios")[1].body?.decisions,
    ).toEqual(fixture.b.decisions);
  });
  test("manual selection previews exact decisions without spending model credits", async () => {
    const user = await openDashboard();
    const card = screen
      .getByRole("heading", { name: "Школа + детсад" })
      .closest("article")!;
    await user.click(
      within(card).getByRole("button", { name: "Добавить решение" }),
    );
    await waitFor(() =>
      expect(requests.some((r) => r.path === "scenario/preview")).toBe(true),
    );
    expect(requests.find((r) => r.path === "scenario/preview")?.body).toEqual({
      decisions: [{ measure_id: "M7", district: "Нура" }],
    });
    expect(
      screen.getByRole("button", { name: "Удалить M7" }),
    ).toBeInTheDocument();
    expect(
      requests.filter((r) => r.path === "ai/runs" || r.path === "ai/explain"),
    ).toHaveLength(0);
  });

  test("text generation polls actual stages, displays fewer than three verified cards and retains session headers", async () => {
    const { cards } = await generate();
    expect(cards).toHaveLength(2);
    expect(screen.getByText("Как понят запрос")).toBeInTheDocument();
    expect(
      screen.getByText("Проверено два разных варианта в пределах лимита."),
    ).toBeInTheDocument();
    const start = requests.find((r) => r.path === "ai/runs")!;
    expect(start.body?.mode).toBe("ai");
    expect(start.body?.request_id).toEqual(expect.any(String));
    expect(new Headers(start.headers).get("X-Session-ID")).toBe("test-session");
    expect(requests.some((r) => r.path === "ai/runs/run-1")).toBe(true);
    expect(requests.some((r) => r.path === "scenario/preview")).toBe(false);
    expect(requests.some((r) => r.path === "optimizer/search")).toBe(false);
  });

  test("comparison uses server scenario IDs and only explains after explicit consent", async () => {
    const { user, cards } = await generate();
    await user.click(
      within(cards[0]).getByRole("button", { name: "Сравнить" }),
    );
    await user.click(
      within(cards[1]).getByRole("button", { name: "Сравнить" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Сравнить выбранные" }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Два пути развития города",
    });
    expect(requests.find((r) => r.path === "scenarios/compare")?.body).toEqual({
      scenario_ids: ["scenario-a", "scenario-b"],
    });
    expect(requests.filter((r) => r.path === "ai/runs")).toHaveLength(1);
    await user.click(
      within(dialog).getByRole("button", { name: "Объяснить с помощью ИИ" }),
    );
    await waitFor(() =>
      expect(requests.filter((r) => r.path === "ai/runs")).toHaveLength(2),
    );
    expect(
      requests.filter((r) => r.path === "ai/runs")[1].body?.operation,
    ).toBe("compare");
  });

  test("applying a generated scenario requires confirmation and cancellation preserves decisions", async () => {
    const { user, cards } = await generate();
    await user.click(
      within(cards[0]).getByRole("button", {
        name: "Применить в центре управления",
      }),
    );
    let dialog = await screen.findByRole("dialog", {
      name: "Заменить текущий план?",
    });
    expect(requests.some((r) => r.path === "scenario/preview")).toBe(false);
    await user.click(
      within(dialog).getByRole("button", { name: "Оставить текущий план" }),
    );
    expect(requests.some((r) => r.path === "scenario/preview")).toBe(false);
    await user.click(
      within(cards[0]).getByRole("button", {
        name: "Применить в центре управления",
      }),
    );
    dialog = await screen.findByRole("dialog", {
      name: "Заменить текущий план?",
    });
    await user.click(
      within(dialog).getByRole("button", { name: "Подтвердить замену" }),
    );
    await waitFor(() =>
      expect(requests.some((r) => r.path === "scenario/preview")).toBe(true),
    );
    expect(
      requests.find((r) => r.path === "scenario/preview")?.body?.decisions,
    ).toEqual(fixture.a.decisions);
    expect(
      screen.getByRole("button", { name: "Удалить M7" }),
    ).toBeInTheDocument();
  });

  test("saving a verified scenario makes it available in the persistent library", async () => {
    const { user, cards } = await generate();
    await user.click(
      within(cards[0]).getByRole("button", { name: "Сохранить" }),
    );
    await within(cards[0]).findByRole("button", { name: "Сохранён" });
    await user.click(
      screen.getByRole("button", { name: "Сохранённые сценарии" }),
    );
    await screen.findByRole("button", { name: "Открыть" });
    expect(saved).toHaveLength(1);
    expect(requests.some((r) => r.path === "scenarios/scenario-a/save")).toBe(
      true,
    );
    expect(requests.some((r) => r.path === "scenarios?saved_only=true")).toBe(
      true,
    );
  });

  test("manual report saves and exports through the server and never starts AI on opening", async () => {
    const user = await openDashboard();
    await user.click(screen.getByRole("button", { name: "Демо-сценарий" }));
    await user.click(
      within(
        await screen.findByRole("dialog", { name: "Заменить текущий план?" }),
      ).getByRole("button", { name: "Подтвердить замену" }),
    );
    const resultButton = screen.getByRole("button", {
      name: "Результат сценария",
    });
    await waitFor(() => expect(resultButton).toBeEnabled());
    await user.click(resultButton);
    const report = await screen.findByRole("dialog", {
      name: "Будущее города в цифрах",
    });
    expect(requests.filter((r) => r.path === "ai/runs")).toHaveLength(0);
    expect(
      within(report).getByText("Точное разложение изменения индекса"),
    ).toBeInTheDocument();
    await user.click(
      within(report).getByRole("button", { name: "Сохранить сценарий" }),
    );
    await within(report).findByText(
      "Сценарий сохранён в библиотеке этой сессии.",
    );
    expect(requests.find((r) => r.path === "scenarios")?.body).toMatchObject({
      provenance: "manual",
      saved: true,
      decisions: fixture.a.decisions,
    });
    Object.defineProperty(URL, "createObjectURL", {
      value: vi.fn(() => "blob:test-scenario"),
      configurable: true,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      value: vi.fn(),
      configurable: true,
    });
    const download = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    await user.click(
      within(report).getByRole("button", { name: "Экспорт JSON" }),
    );
    await waitFor(() => expect(download).toHaveBeenCalledOnce());
    expect(
      requests.some((r) => r.path === "scenarios/manual-scenario/export"),
    ).toBe(true);
    const print = vi.spyOn(window, "print").mockImplementation(() => {});
    await user.click(
      within(report).getByRole("button", { name: "Печатный отчёт" }),
    );
    expect(print).toHaveBeenCalledOnce();
    expect(requests.filter((r) => r.path === "ai/runs")).toHaveLength(0);
  });

  test("AI failure is explicit, has no hidden fallback and leaves manual mode usable", async () => {
    failAI = true;
    const user = await openDashboard();
    await user.click(
      screen.getAllByRole("button", {
        name: "Лаборатория сценариев",
      })[0],
    );
    await user.type(
      screen.getByLabelText("Ваш запрос или уточнение"),
      "Предложи варианты",
    );
    await user.click(screen.getByRole("button", { name: "Отправить запрос" }));
    await screen.findByText("Операция не выполнена");
    expect(
      screen.queryByText(/QUOTA_EXCEEDED|Квота провайдера|Провайдер отклонил/),
    ).not.toBeInTheDocument();
    expect(requests.filter((r) => r.path === "ai/runs")).toHaveLength(1);
    expect(requests.some((r) => r.path === "optimizer/search")).toBe(false);
    await user.click(
      screen.getAllByRole("button", {
        name: "Центр управления",
      })[0],
    );
    expect(
      screen.getByRole("heading", { name: "Районы города" }),
    ).toBeVisible();
  });

  test("run cancellation calls its endpoint and stops polling", async () => {
    remainRunning = true;
    const user = await openDashboard();
    await user.click(
      screen.getAllByRole("button", {
        name: "Лаборатория сценариев",
      })[0],
    );
    fireEvent.change(screen.getByLabelText("Ваш запрос или уточнение"), {
      target: { value: "Предложи варианты" },
    });
    await user.click(screen.getByRole("button", { name: "Отправить запрос" }));
    await user.click(await screen.findByRole("button", { name: "Отменить" }));
    await screen.findByText("Операция отменена");
    expect(requests.some((r) => r.path === "ai/runs/run-1/cancel")).toBe(true);
  });

  test("restored failures never expose diagnostics through status, events or assistant history", async () => {
    const diagnostic =
      "Объяснение содержит неизвестную ссылку на факт: A.activated_synergies[0].effects.B1; A.critical_after[0].value (UNGROUNDED_EXPLANATION)";
    restoredRuns = [
      {
        ...run("failed"),
        message: diagnostic,
        error: { code: "UNGROUNDED_EXPLANATION", message: diagnostic },
        events: [
          { stage: "repairing", message: diagnostic },
          { stage: "failed", message: diagnostic },
        ],
      },
    ];
    history = [
      { role: "user", content: "Покажи варианты для Нуры" },
      { role: "assistant", content: diagnostic },
      { role: "assistant", content: "legacy-secret-diagnostic", kind: "error" },
    ];
    const user = await openDashboard();
    await user.click(
      screen.getAllByRole("button", { name: "Лаборатория сценариев" })[0],
    );
    await screen.findByText(
      "Попробуйте отправить запрос ещё раз. Ручной режим остаётся доступен.",
    );
    await user.click(screen.getByText("Этапы выполнения"));
    expect(document.body.textContent).not.toMatch(
      /UNGROUNDED_EXPLANATION|activated_synergies|critical_after|legacy-secret-diagnostic/,
    );
    expect(
      within(screen.getByLabelText("История диалога")).getByText(
        "Покажи варианты для Нуры",
      ),
    ).toBeVisible();
    expect(screen.getByText("Исправление вариантов")).toBeVisible();
  });

  test("follow-up keeps previous hard constraints and displays clarification with conversation history", async () => {
    const { user } = await generate();
    await user.type(
      screen.getByLabelText("Ваш запрос или уточнение"),
      "Теперь резерв 20, остальные ограничения сохрани и перенеси меру.",
    );
    await user.click(screen.getByRole("button", { name: "Отправить запрос" }));
    await screen.findByText("Какую меру нужно перенести?");
    const last = requests.filter((r) => r.path === "ai/runs").at(-1)!;
    expect(last.body?.constraints).toMatchObject({
      max_budget: 100,
      excluded_measure_ids: ["M3"],
      focus_district: "Нура",
    });
    const reserveLabel = screen.getByText("Минимальный резерв");
    expect(reserveLabel.nextElementSibling).toHaveTextContent("20");
    expect(
      screen.getByText("Исключённые меры").nextElementSibling,
    ).toHaveTextContent("M3");
    expect(
      within(screen.getByLabelText("История диалога")).getByText(
        /остальные ограничения сохрани и перенеси/,
      ),
    ).toBeInTheDocument();
    expect(requests.filter((r) => r.path === "ai/runs")).toHaveLength(2);
  });
});
