import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { ComparisonChart, DistrictRadar } from "@/components/charts";
import model from "./fixtures/model.json";

type Size = { width: number; height: number };
let boxes: WeakMap<Element, Size>;
let initialSize: Size;
let observers: Set<ObservedSize>;
let printListeners: Set<(event: MediaQueryListEvent) => void>;

class ObservedSize implements ResizeObserver {
  targets = new Set<Element>();
  constructor(readonly callback: ResizeObserverCallback) {
    observers.add(this);
  }
  observe(target: Element) {
    this.targets.add(target);
  }
  unobserve(target: Element) {
    this.targets.delete(target);
  }
  disconnect = vi.fn(() => this.targets.clear());
}

beforeEach(() => {
  boxes = new WeakMap();
  initialSize = { width: 0, height: 0 };
  observers = new Set();
  printListeners = new Set();
  vi.stubGlobal("ResizeObserver", ObservedSize);
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: false,
      media: "print",
      addEventListener: (
        _name: string,
        listener: (event: MediaQueryListEvent) => void,
      ) => printListeners.add(listener),
      removeEventListener: (
        _name: string,
        listener: (event: MediaQueryListEvent) => void,
      ) => printListeners.delete(listener),
    })),
  );
  // jsdom has no layout engine. Only the chart host receives a simulated
  // layout box; Recharts itself is real and its output is asserted below.
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    function (this: HTMLElement) {
      const size =
        this.getAttribute("role") === "img" && !this.closest("[hidden]")
          ? (boxes.get(this) ?? initialSize)
          : { width: 0, height: 0 };
      return new DOMRect(0, 0, size.width, size.height);
    },
  );
});

afterEach(() => vi.unstubAllGlobals());

function notifyResize(host: HTMLElement) {
  act(() => {
    for (const observer of [...observers]) {
      if (observer.targets.has(host)) {
        const contentRect = host.getBoundingClientRect();
        const boxSize = [
          { inlineSize: contentRect.width, blockSize: contentRect.height },
        ];
        observer.callback(
          [
            {
              target: host,
              contentRect,
              borderBoxSize: boxSize,
              contentBoxSize: boxSize,
              devicePixelContentBoxSize: boxSize,
            },
          ],
          observer,
        );
      }
    }
  });
}

function resize(host: HTMLElement, width: number, height: number) {
  boxes.set(host, { width, height });
  notifyResize(host);
}

function expectChartSize(host: HTMLElement, width: number, height: number) {
  const svg = host.querySelector(".recharts-wrapper > svg.recharts-surface");
  expect(svg).toHaveAttribute("width", String(width));
  expect(svg).toHaveAttribute("height", String(height));
  expect(svg).toHaveAttribute("viewBox", `0 0 ${width} ${height}`);
}

const chartTypes = [
  {
    name: "radar",
    element: () => <DistrictRadar district={model.base.districts.Нура} />,
    marks: ".recharts-radar-polygon",
  },
  {
    name: "comparison",
    element: () => (
      <ComparisonChart data={[{ name: "Транспорт", before: 40, after: 63 }]} />
    ),
    marks: ".recharts-bar-rectangle path",
  },
];

describe.each(chartTypes)("$name chart dimensions", ({ element, marks }) => {
  test("waits for both measured dimensions, resizes, and remounts after a hidden tab returns", () => {
    const warnings = vi.spyOn(console, "warn");
    const { rerender } = render(<section>{element()}</section>);
    const host = screen.getByRole("img");
    expect(host.querySelector(".recharts-wrapper")).toBeNull();

    resize(host, 0, 250);
    expect(host.querySelector("svg")).toBeNull();
    resize(host, 350, 0);
    expect(host.querySelector("svg")).toBeNull();

    resize(host, 312.5, 238.25);
    expectChartSize(host, 312.5, 238.25);
    expect(host.querySelector(marks)).not.toBeNull();

    resize(host, 640, 280);
    expectChartSize(host, 640, 280);

    rerender(<section hidden>{element()}</section>);
    notifyResize(host);
    expect(host.querySelector(".recharts-wrapper")).toBeNull();

    // The observed host survives hiding, so no window resize is needed.
    rerender(<section>{element()}</section>);
    resize(host, 410, 255);
    expectChartSize(host, 410, 255);
    expect(host.querySelector(marks)).not.toBeNull();
    expect(warnings).not.toHaveBeenCalled();
  });

  test("an initially hidden chart mounts when its tab becomes visible", () => {
    initialSize = { width: 420, height: 260 };
    const warnings = vi.spyOn(console, "warn");
    const { container, rerender } = render(
      <section hidden>{element()}</section>,
    );
    const host = container.querySelector('[role="img"]') as HTMLElement;
    expect(host.querySelector("svg")).toBeNull();
    rerender(<section>{element()}</section>);
    notifyResize(host);
    expectChartSize(host, 420, 260);
    expect(warnings).not.toHaveBeenCalled();
  });
});

test("server rendering needs no DOM measurements and emits no chart warnings", () => {
  const warnings = vi.spyOn(console, "warn");
  const errors = vi.spyOn(console, "error");
  const html = renderToString(
    <>
      {chartTypes[0].element()}
      {chartTypes[1].element()}
    </>,
  );
  expect(html).toContain('role="img"');
  expect(html).not.toContain("<svg");
  expect(HTMLElement.prototype.getBoundingClientRect).not.toHaveBeenCalled();
  expect(observers.size).toBe(0);
  expect(warnings).not.toHaveBeenCalled();
  expect(errors).not.toHaveBeenCalled();
});

test("print events commit real print dimensions synchronously and restore screen layout", () => {
  initialSize = { width: 420, height: 250 };
  const warnings = vi.spyOn(console, "warn");
  render(chartTypes[1].element());
  const host = screen.getByRole("img");
  expectChartSize(host, 420, 250);

  boxes.set(host, { width: 680, height: 250 });
  act(() => {
    window.dispatchEvent(new Event("beforeprint"));
    // This assertion is deliberately inside act: a browser may take its
    // print snapshot before React otherwise finishes the event's batch.
    expectChartSize(host, 680, 250);
    expect(host.querySelector(".recharts-bar-rectangle path")).not.toBeNull();
  });

  // The print media notification also covers engines which apply their
  // print layout after beforeprint, and reopening print preview.
  boxes.set(host, { width: 720, height: 270 });
  act(() => {
    for (const listener of printListeners) {
      listener({ matches: true } as MediaQueryListEvent);
    }
    expectChartSize(host, 720, 270);
  });

  boxes.set(host, { width: 420, height: 250 });
  act(() => {
    window.dispatchEvent(new Event("afterprint"));
    expectChartSize(host, 420, 250);
  });
  expect(warnings).not.toHaveBeenCalled();
});

test("zero-sized print layout does not retain a stale chart", () => {
  initialSize = { width: 420, height: 250 };
  render(chartTypes[0].element());
  const host = screen.getByRole("img");
  boxes.set(host, { width: 0, height: 0 });
  act(() => window.dispatchEvent(new Event("beforeprint")));
  expect(host.querySelector("svg")).toBeNull();
  boxes.set(host, { width: 420, height: 250 });
  act(() => window.dispatchEvent(new Event("afterprint")));
  expectChartSize(host, 420, 250);
});

test("window resizing can measure the chart when ResizeObserver is unavailable", () => {
  vi.stubGlobal("ResizeObserver", undefined);
  render(chartTypes[1].element());
  const host = screen.getByRole("img");
  expect(host.querySelector("svg")).toBeNull();
  boxes.set(host, { width: 480, height: 250 });
  act(() => window.dispatchEvent(new Event("resize")));
  expectChartSize(host, 480, 250);
});

test("unmount disconnects measurement and print listeners", () => {
  const { unmount } = render(chartTypes[0].element());
  const observer = [...observers][0];
  expect(printListeners.size).toBe(1);
  unmount();
  expect(observer.disconnect).toHaveBeenCalledOnce();
  expect(printListeners.size).toBe(0);
  const reads = vi.mocked(HTMLElement.prototype.getBoundingClientRect).mock
    .calls.length;
  act(() => {
    window.dispatchEvent(new Event("resize"));
    window.dispatchEvent(new Event("beforeprint"));
    window.dispatchEvent(new Event("afterprint"));
  });
  expect(HTMLElement.prototype.getBoundingClientRect).toHaveBeenCalledTimes(
    reads,
  );
});
