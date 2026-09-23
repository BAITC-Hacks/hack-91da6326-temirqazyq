import type { ReactNode } from 'react'

/* Боковая навигация вместо пяти коротких ссылок в шапке.
   Здесь есть место объяснить каждый шаг словами и показать его состояние,
   поэтому «2 · Результат и AI» превращается в понятный пункт маршрута. */
export type NavStep = {
  id: string
  label: string
  hint: string
  /* доступен ли шаг и почему нет */
  locked?: string
  done?: boolean
  badge?: ReactNode
}

export default function SideNav({
  steps,
  active,
  onPick,
}: {
  steps: NavStep[]
  active: string
  onPick: (id: string) => void
}) {
  return (
    <nav className="sidenav" data-tour="nav" aria-label="Шаги симулятора">
      <ol>
        {steps.map((s, i) => {
          const isActive = s.id === active
          return (
            <li key={s.id}>
              <button
                className={`navstep${isActive ? ' active' : ''}${s.locked ? ' locked' : ''}`}
                onClick={() => !s.locked && onPick(s.id)}
                disabled={!!s.locked}
                title={s.locked}
                aria-current={isActive ? 'step' : undefined}
              >
                <span className={`n${s.done ? ' done' : ''}`}>{s.done ? '✓' : i + 1}</span>
                <span className="body">
                  <span className="t">
                    {s.label}
                    {s.badge}
                  </span>
                  <span className="h">{s.locked ?? s.hint}</span>
                </span>
              </button>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
