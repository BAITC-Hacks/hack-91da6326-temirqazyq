import { useState } from 'react'
import type { Decision, Meta, ValidationResult, World } from '../api'
import { DIR_COLORS, districtName, measureName } from '../lib'

type Props = {
  meta: Meta
  world: World | null
  decisions: Decision[]
  validation: ValidationResult | null
  busy: boolean
  onChange: (d: Decision[]) => void
  onScore: () => void
}

export default function Planner({ meta, world, decisions, validation, busy, onChange, onScore }: Props) {
  const [pick, setPick] = useState<Record<string, string>>({})
  const budget = world?.budget ?? meta.rules.budget
  const blocked = new Set(world?.blocked_measures ?? [])
  const chosen = new Map(decisions.map((d) => [d.measure_id, d]))
  const N = meta.rules.decisions_required

  const add = (mid: string, district: string | null) => {
    if (decisions.length >= N || chosen.has(mid)) return
    onChange([...decisions, { measure_id: mid, district_id: district }])
  }
  const remove = (i: number) => onChange(decisions.filter((_, j) => j !== i))
  const cost = validation?.total_cost ?? decisions.reduce((s, d) => s + (meta.measures.find((m) => m.id === d.measure_id)?.cost ?? 0), 0)
  const pct = Math.min(100, (cost / budget) * 100)

  return (
    <div className="grid planner">
      <div>
        {Object.entries(meta.directions).map(([dir, title]) => (
          <div className="dir-block" key={dir}>
            <h3><i style={{ background: DIR_COLORS[dir] }} />{title} <span className="muted" style={{ textTransform: 'none', letterSpacing: 0 }}>· не более {meta.rules.max_per_direction}</span></h3>
            <div className="measures">
              {meta.measures.filter((m) => m.direction === dir).map((m) => {
                const sel = chosen.get(m.id)
                const isBlocked = blocked.has(m.id)
                const full = decisions.length >= N
                return (
                  <div key={m.id} className={`measure ${sel ? 'selected' : ''} ${isBlocked ? 'blocked' : ''}`} style={{ ['--dir' as string]: DIR_COLORS[dir] }}>
                    <div className="row spread">
                      <span className="name">{m.id} · {m.name}</span>
                      <span className="chip">{m.scope === 'city' ? 'город' : 'район'}</span>
                    </div>
                    <div className="row small muted">
                      <span>💰 {m.cost}</span><span>⏱ лаг {m.lag} кв. → эффект ×{((meta.rules.horizon_quarters - m.lag) / meta.rules.horizon_quarters).toFixed(2)}</span>
                    </div>
                    <div className="fx">
                      {Object.entries(m.effects).map(([k, v]) => <span key={k} className={`chip ${v >= 0 ? 'pos' : 'neg'}`}>{k} {v > 0 ? '+' : ''}{v}</span>)}
                    </div>
                    <div className="actions">
                      {isBlocked ? <span className="small error">Заблокировано событием</span> : sel ? (
                        <>
                          <span className="small muted">Выбрано: {districtName(meta, sel.district_id)}</span>
                          <button className="small" onClick={() => remove(decisions.indexOf(sel))}>Убрать</button>
                        </>
                      ) : (
                        <>
                          {m.scope === 'district' && (
                            <select value={pick[m.id] ?? ''} onChange={(e) => setPick({ ...pick, [m.id]: e.target.value })}>
                              <option value="">Район…</option>
                              {meta.districts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                            </select>
                          )}
                          <button className="small primary" disabled={full || (m.scope === 'district' && !pick[m.id])} onClick={() => add(m.id, m.scope === 'district' ? pick[m.id] : null)}>
                            Добавить
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>

      <div className="panel sticky">
        <div className="row spread mb">
          <h2>Пять решений</h2>
          <span className="muted small">{decisions.length}/{N}</span>
        </div>
        <div className="slots">
          {Array.from({ length: N }).map((_, i) => {
            const d = decisions[i]
            const m = d && meta.measures.find((x) => x.id === d.measure_id)
            return (
              <div key={i} className={`slot ${d ? 'filled' : ''}`} style={{ ['--dir' as string]: m ? DIR_COLORS[m.direction] : undefined }}>
                <span className="n">{i + 1}</span>
                {d && m ? (
                  <>
                    <div className="body">
                      <div>{d.measure_id} · {measureName(meta, d.measure_id)}</div>
                      <div className="small muted">{districtName(meta, d.district_id)} · {m.cost} ед. · лаг {m.lag}</div>
                    </div>
                    <button className="small ghost" onClick={() => remove(i)}>✕</button>
                  </>
                ) : <span className="muted small">Пустой слот — выберите мероприятие в каталоге</span>}
              </div>
            )
          })}
        </div>

        <div className="mt row spread"><span className="small muted">Бюджет</span><b className="num">{cost} / {budget}</b></div>
        <div className="budget"><i className={cost > budget ? 'over' : ''} style={{ width: `${pct}%` }} /></div>
        <div className="small muted mt" style={{ marginTop: 4 }}>Остаток {budget - cost} — не переносится и бонуса не даёт</div>

        <div className="dircount mt">
          {Object.entries(meta.directions).map(([dir, title]) => {
            const n = validation?.per_direction[dir] ?? decisions.filter((d) => meta.measures.find((m) => m.id === d.measure_id)?.direction === dir).length
            return <div key={dir} className={n > meta.rules.max_per_direction ? 'over' : ''} style={{ ['--dir' as string]: DIR_COLORS[dir] }} title={title}><b>{n}</b>{({ transport: 'Трансп.', ecology: 'Эколог.', social: 'Соц.', safety: 'Безоп.', services: 'Сервис' } as Record<string, string>)[dir]}</div>
          })}
        </div>

        <div className="mt issues">
          {validation && validation.valid && <div className="ok">Набор валиден — можно считать Score</div>}
          {validation?.issues.map((i, k) => <div key={k} className="issue">{i.message}</div>)}
        </div>

        <div className="mt row">
          <button className="primary" disabled={!validation?.valid || busy} onClick={onScore} style={{ flex: 1 }}>
            {busy ? <span className="spinner" /> : 'Рассчитать Astana QoL Score'}
          </button>
          <button className="ghost" onClick={() => onChange([])} disabled={!decisions.length}>Сброс</button>
        </div>
      </div>
    </div>
  )
}
