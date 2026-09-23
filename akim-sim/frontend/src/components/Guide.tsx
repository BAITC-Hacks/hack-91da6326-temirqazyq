import { Tooltip } from 'antd'
import type { Guide, GuideBundle, Meta } from '../api'
import type { Decision } from '../api'
import { DIR_COLORS, signed } from '../lib'
import { Hint } from './Viz'

/* Панель «куда смотреть». Всё здесь посчитал движок: и слабые места районов,
   и готовые наборы под конкретную цель. LLM не участвует. */
export function DistrictAdvice({ guide, meta }: { guide: Guide; meta: Meta }) {
  return (
    <div className="adv-grid">
        {guide.districts.map((d) => {
          const m = d.best_move && meta.measures.find((x) => x.id === d.best_move!.measure_id)
          return (
            <div className="adv" key={d.district_id}>
              <div className="row spread">
                <b>{d.name}</b>
                <span className="num small muted">{d.score}</span>
              </div>
              <div className="adv-weak">
                {d.weakest.map((w) => (
                  <Tooltip key={w.code} title={`${w.name}: сейчас ${w.value}`}>
                    <span className={`w ${w.critical ? 'crit' : ''}`}>
                      {w.code} {w.value}
                    </span>
                  </Tooltip>
                ))}
              </div>
              {d.best_move && m ? (
                <div className="tiny">
                  Лучший ход сюда: <b>{m.id}</b> {m.name} —{' '}
                  <span className="pos num">{signed(d.best_move.delta)}</span>
                </div>
              ) : (
                <div className="tiny dim">Подходящих ходов в пределах остатка нет</div>
              )}
            </div>
          )
        })}
    </div>
  )
}

export function Bundles({
  bundles,
  onTake,
}: {
  bundles: GuideBundle[]
  onTake: (d: Decision[]) => void
}) {
  if (!bundles.length) return null
  return (
    <div className="bundles">
        {bundles.map((b) => (
          <div className="bundle" key={b.goal}>
            <b>{b.title}</b>
            <p className="tiny muted">{b.why}</p>
            <div className="bundle-nums">
              <span><b className="num">{b.score}</b> оценка</span>
              <span><b className="num">{b.cost}</b> цена</span>
              <span><b className="num">{b.d_min}</b> <Hint term="dmin">слабейший</Hint></span>
              <span className={b.n_crit ? 'neg' : 'pos'}><b className="num">{b.n_crit}</b> провалов</span>
            </div>
            <button className="small primary take" onClick={() => onTake(b.decisions)}>
              Взять этот набор
            </button>
            <ul className="tiny muted">{b.human.map((h, i) => <li key={i}>{h}</li>)}</ul>
          </div>
        ))}
    </div>
  )
}

/* Шаги по направлениям с кнопками «Назад / Далее»: видно, где ты сейчас,
   сколько шагов всего и докуда дошёл. Выбор идёт по одному направлению за раз. */
export function DirectionSteps({
  meta,
  active,
  counts,
  onPick,
}: {
  meta: Meta;
  active: string;
  counts: Record<string, number>;
  onPick: (dir: string) => void;
}) {
  const dirs = Object.entries(meta.directions);
  const i = Math.max(0, dirs.findIndex(([d]) => d === active));
  const [curDir, curTitle] = dirs[i];
  const total = Object.values(counts).reduce((a, b) => a + b, 0);

  return (
    <div className="stepper">
      <div className="stepper-rail">
        {dirs.map(([dir, title], k) => (
          <button
            key={dir}
            className={`srail${k === i ? ' active' : ''}${counts[dir] ? ' filled' : ''}`}
            style={{ ['--dir' as string]: DIR_COLORS[dir] }}
            onClick={() => onPick(dir)}
            title={title}
            aria-current={k === i ? 'step' : undefined}
          >
            <i />
            <span className="k">{k + 1}</span>
            <span className="nm">{title}</span>
            {counts[dir] > 0 && <span className="cn">{counts[dir]}</span>}
          </button>
        ))}
      </div>

      <div className="stepper-head">
        <div>
          <span className="eyebrow">
            Шаг {i + 1} из {dirs.length} · выбрано {total} из {meta.rules.decisions_required}
          </span>
          <h3 className="stepper-title" style={{ ['--dir' as string]: DIR_COLORS[curDir] }}>
            <i />
            {curTitle}
          </h3>
          <span className="small muted">
            {counts[curDir] ?? 0} из максимум {meta.rules.max_per_direction} в этом направлении
          </span>
        </div>
        <div className="row">
          <button className="small" disabled={i === 0} onClick={() => onPick(dirs[i - 1][0])}>
            ← Назад
          </button>
          <button
            className="small primary"
            disabled={i === dirs.length - 1}
            onClick={() => onPick(dirs[i + 1][0])}
          >
            Далее →
          </button>
        </div>
      </div>
    </div>
  );
}
