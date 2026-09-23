import type { ReactNode } from 'react'
import { Tooltip } from 'antd'
import type { Meta } from '../api'
import { TERMS, heatFill, signed } from '../lib'

/* ——— Расшифровка термина движка.
   Всплывашка — antd Tooltip: он рендерится в портал, поэтому не раздвигает страницу
   и сам разворачивается у края экрана. Пунктирное подчёркивание остаётся приглашением. ——— */
export function Hint({
  term,
  children,
}: {
  term: keyof typeof TERMS | string
  children: ReactNode
  /** Оставлено для совместимости: antd сам выбирает сторону. */
  side?: 'left' | 'right'
}) {
  const text = TERMS[term]
  if (!text) return <>{children}</>
  return (
    <Tooltip title={text} placement="top" mouseEnterDelay={0.15}>
      <span className="hint" tabIndex={0} role="note">
        {children}
      </span>
    </Tooltip>
  )
}

/* ——— Dumbbell «до → после».
   Форма выбрана вместо бара с ненулевой базой и вместо радара: значение несёт
   положение точки, поэтому обрезанный диапазон не врёт длиной. Один тон, две ступени. ——— */
export type DumbRow = { label: string; before: number; after: number }

export function Dumbbell({ rows, unit = '', digits = 2 }: { rows: DumbRow[]; unit?: string; digits?: number }) {
  const values = rows.flatMap((r) => [r.before, r.after])
  const rawLo = Math.min(...values)
  const rawHi = Math.max(...values)
  const pad = Math.max((rawHi - rawLo) * 0.15, 1)
  const lo = rawLo - pad
  const hi = rawHi + pad
  const pos = (v: number) => ((v - lo) / (hi - lo)) * 100

  return (
    <div>
      <div className="dumb-scale">
        <span>{lo.toFixed(0)}</span>
        <span>{hi.toFixed(0)}</span>
      </div>
      <div className="dumb">
        {rows.map((r) => {
          const a = pos(r.before)
          const b = pos(r.after)
          const delta = r.after - r.before
          const down = delta < 0
          return (
            <div className="dumb-row" key={r.label}>
              <span className="lbl" title={r.label}>{r.label}</span>
              <div className="dumb-track">
                <span className="axis" />
                <span
                  className={`conn${down ? ' down' : ''}`}
                  style={{ left: `${Math.min(a, b)}%`, width: `${Math.abs(b - a)}%` }}
                />
                <span className="pt a" style={{ left: `${a}%` }} title={`до: ${r.before.toFixed(digits)}${unit}`} />
                <span className="pt b" style={{ left: `${b}%` }} title={`после: ${r.after.toFixed(digits)}${unit}`} />
              </div>
              <span className="val">
                {r.after.toFixed(digits)}{' '}
                <span className={`tiny ${Math.abs(delta) < 0.05 ? 'dim' : down ? 'neg' : 'pos'}`}>
                  {signed(delta, 1)}
                </span>
              </span>
            </div>
          )
        })}
      </div>
      <div className="legend mt">
        <span><i style={{ background: 'var(--before)' }} />до решений</span>
        <span><i style={{ background: 'var(--after)' }} />после</span>
        <span className="dim">значение справа — «после» и сдвиг</span>
      </div>
    </div>
  )
}

/* ——— Диверегирующие бары: знак означает «помогло / навредило», поэтому полюса статусные,
   а не по направлению. Сторона от нулевой линии дублирует знак цветом. ——— */
export type DivRow = { label: string; value: number; color?: string; hint?: string }

export function DivergingBars({ rows }: { rows: DivRow[] }) {
  const values = rows.map((r) => r.value)
  const lo = Math.min(0, ...values)
  const hi = Math.max(0, ...values)
  const span = hi - lo || 1
  const zero = ((0 - lo) / span) * 100

  return (
    <div className="div-rows">
      {rows.map((r) => {
        const v = ((r.value - lo) / span) * 100
        const up = r.value >= 0
        return (
          <div className="div-row" key={r.label} title={r.hint ? `${r.label} — ${r.hint}` : r.label}>
            <span className="lbl">
              {r.color && <i style={{ background: r.color }} />}
              {r.label}
            </span>
            <div className="div-track">
              <span className="zero" style={{ left: `${zero}%` }} />
              <span
                className={`bar ${up ? 'up' : 'down'}`}
                style={{ left: `${up ? zero : v}%`, width: `${Math.max(Math.abs(v - zero), 0.6)}%` }}
              />
            </div>
            <span className={`val ${up ? 'pos' : 'neg'}`}>{signed(r.value)}</span>
          </div>
        )
      })}
    </div>
  )
}

/* ——— Легенда тепловой карты. Семантический heat разрешён только вместе со шкалой,
   поэтому легенда обязана стоять рядом с картой, а не быть опциональной. ——— */
export function HeatLegend({ threshold }: { threshold: number }) {
  const ramp = `linear-gradient(90deg, ${heatFill(30)}, ${heatFill(55)}, ${heatFill(80)})`
  return (
    <div className="heat-legend">
      <span>30</span>
      <span className="ramp" style={{ background: ramp }} />
      <span>80</span>
      <span className="dim">·</span>
      <span>рамка — значение ниже {threshold}, штраф −1</span>
    </div>
  )
}

/* ——— Расшифровка кодов показателей: раньше была только в title, теперь видна. ——— */
export function CodesLegend({ meta }: { meta: Meta }) {
  return (
    <div className="codes">
      {meta.indicators.map((i) => (
        <div key={i.code}>
          <b>{i.code}</b> {i.name}
        </div>
      ))}
    </div>
  )
}
