import { Tooltip } from 'antd'
import type { Guide, GuideBundle, Meta } from '../api'
import type { Decision } from '../api'
import { DIR_COLORS, signed } from '../lib'
import { Hint } from './Viz'

/* Панель «куда смотреть». Всё здесь посчитал движок: и слабые места районов,
   и готовые наборы под конкретную цель. LLM не участвует. */
export function DistrictAdvice({ guide, meta }: { guide: Guide; meta: Meta }) {
  return (
    <section className="panel mb">
      <h2 className="mb">Куда смотреть</h2>
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
    </section>
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
    <section className="panel mb">
      <h2 className="mb">Готовые наборы под цель</h2>
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
    </section>
  )
}

/* Полоса шагов по направлениям: за раз показывается одно, чтобы не выбирать вслепую из четырнадцати. */
export function DirectionSteps({
  meta,
  active,
  counts,
  onPick,
}: {
  meta: Meta
  active: string
  counts: Record<string, number>
  onPick: (dir: string) => void
}) {
  const dirs = Object.entries(meta.directions)
  return (
    <div className="dirsteps" role="tablist">
      {dirs.map(([dir, title], i) => (
        <button
          key={dir}
          role="tab"
          aria-selected={dir === active}
          className={`dirstep${dir === active ? ' active' : ''}${counts[dir] ? ' filled' : ''}`}
          style={{ ['--dir' as string]: DIR_COLORS[dir] }}
          onClick={() => onPick(dir)}
        >
          <i />
          <span className="t">{i + 1}. {title}</span>
          <span className="c">{counts[dir] ?? 0}/{meta.rules.max_per_direction}</span>
        </button>
      ))}
    </div>
  )
}
