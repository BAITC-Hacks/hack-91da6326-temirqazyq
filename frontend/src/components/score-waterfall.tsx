import type { SimulationResult } from "@/lib/types";
import { fmt, signed } from "@/lib/ui";

export default function ScoreWaterfall({
  result,
}: {
  result: SimulationResult;
}) {
  const decomposition = result.score_decomposition;
  if (!decomposition)
    return (
      <p className="muted">
        Для этого расчёта сервер не вернул точное разложение индекса.
      </p>
    );
  const values = [
    decomposition.average,
    decomposition.weakest,
    decomposition.critical,
  ];
  const labels = ["Средний индекс", "Слабейший район", "Критические значения"];
  const positions = values.reduce<number[]>(
    (points, value) => [...points, points[points.length - 1] + value],
    [result.score.before],
  );
  const min = Math.min(...positions, result.score.after) - 1;
  const max = Math.max(...positions, result.score.after) + 1;
  const y = (value: number) => 180 - ((value - min) / (max - min)) * 135;
  const steps = [
    {
      label: "До решений",
      from: min,
      to: result.score.before,
      value: result.score.before,
      total: true,
    },
    ...values.map((value, i) => ({
      label: labels[i],
      from: positions[i],
      to: positions[i + 1],
      value,
      total: false,
    })),
    {
      label: "После решений",
      from: min,
      to: result.score.after,
      value: result.score.after,
      total: true,
    },
  ];
  return (
    <section className="panel score-waterfall">
      <h3>Точное разложение изменения индекса</h3>
      <p className="muted small">
        Составляющие рассчитаны сервером по формуле модели. Их сумма равна
        общему изменению.
      </p>
      <div className="waterfall-scroll">
        <svg
          viewBox="0 0 670 235"
          role="img"
          aria-label="Каскадная диаграмма изменения итогового индекса"
        >
          <line x1="15" y1="180" x2="655" y2="180" stroke="#e3e9ee" />
          {steps.map((step, i) => {
            const x = 23 + i * 132;
            const top = Math.min(y(step.from), y(step.to));
            const height = Math.max(2, Math.abs(y(step.to) - y(step.from)));
            return (
              <g key={step.label}>
                <rect
                  x={x + 21}
                  y={top}
                  width="73"
                  height={height}
                  rx="4"
                  fill={
                    step.total
                      ? "#53788e"
                      : step.value >= 0
                        ? "#27ab91"
                        : "#c59050"
                  }
                />
                <text
                  x={x + 57}
                  y={top - 9}
                  textAnchor="middle"
                  fill="#3f6573"
                  fontSize="13"
                  fontWeight="600"
                >
                  {step.total ? fmt(step.value) : signed(step.value)}
                </text>
                <text
                  x={x + 57}
                  y="208"
                  textAnchor="middle"
                  fill="#6e8190"
                  fontSize="10"
                >
                  {step.label}
                </text>
                {i < 4 && (
                  <line
                    x1={x + 94}
                    x2={x + 153}
                    y1={y(step.to)}
                    y2={y(step.to)}
                    stroke="#a6bfc1"
                    strokeDasharray="3 3"
                  />
                )}
              </g>
            );
          })}
        </svg>
      </div>
      <dl className="decomposition-values">
        <div>
          <dt>0,7 × изменение среднего индекса</dt>
          <dd>{signed(decomposition.average, 4)}</dd>
        </div>
        <div>
          <dt>0,3 × изменение минимума по районам</dt>
          <dd>{signed(decomposition.weakest, 4)}</dd>
        </div>
        <div>
          <dt>Уменьшение числа критических значений</dt>
          <dd>{signed(decomposition.critical, 4)}</dd>
        </div>
        <div>
          <dt>Итого</dt>
          <dd>{signed(decomposition.total, 4)}</dd>
        </div>
      </dl>
    </section>
  );
}
