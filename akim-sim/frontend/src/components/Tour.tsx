import { useCallback, useEffect, useState } from 'react'

/* Пошаговый тур с подсветкой. Каждый шаг привязан к элементу через data-tour,
   а не через CSS-класс: класс может смениться при вёрстке, атрибут ставится осознанно. */
export type TourStep = {
  target: string
  title: string
  text: string
  /* шаг показывается, только если элемент на экране; остальные пропускаются */
}

const PAD = 8

export default function Tour({ steps, onDone }: { steps: TourStep[]; onDone: () => void }) {
  const [i, setI] = useState(0)
  const [rect, setRect] = useState<DOMRect | null>(null)

  /* Только измеряем. Прокрутка вынесена отдельно: раньше scrollIntoView вызывался
     на каждом кадре и перезапускал сам себя — отсюда рывки подсветки. */
  const locate = useCallback(() => {
    const el = document.querySelector<HTMLElement>(`[data-tour="${steps[i]?.target}"]`)
    if (!el) { setRect(null); return }
    const r = el.getBoundingClientRect()
    setRect((prev) =>
      prev && Math.abs(prev.top - r.top) < 0.5 && Math.abs(prev.left - r.left) < 0.5 &&
      Math.abs(prev.width - r.width) < 0.5 && Math.abs(prev.height - r.height) < 0.5
        ? prev   // ничего не сдвинулось — не дёргаем рендер
        : r,
    )
  }, [i, steps])

  // Прокрутка — ровно один раз на шаг.
  useEffect(() => {
    const el = document.querySelector<HTMLElement>(`[data-tour="${steps[i]?.target}"]`)
    if (!el) return
    const r = el.getBoundingClientRect()
    const hidden = r.top < 80 || r.bottom > window.innerHeight - 80
    if (hidden) el.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [i, steps])

  // Измеряем, пока координаты едут, но без лишних рендеров и без повторной прокрутки.
  useEffect(() => {
    locate()
    let raf = 0
    let last = -1
    const started = performance.now()
    const chase = (now: number) => {
      if (now - last > 32) { locate(); last = now }   // ~30 к/с достаточно
      if (now - started < 800) raf = requestAnimationFrame(chase)
    }
    raf = requestAnimationFrame(chase)
    window.addEventListener('resize', locate)
    window.addEventListener('scroll', locate, true)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', locate)
      window.removeEventListener('scroll', locate, true)
    }
  }, [locate])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onDone()
      if (e.key === 'ArrowRight' || e.key === 'Enter') setI((v) => (v + 1 < steps.length ? v + 1 : (onDone(), v)))
      if (e.key === 'ArrowLeft') setI((v) => Math.max(0, v - 1))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [steps.length, onDone])

  const step = steps[i]
  if (!step) return null

  const last = i === steps.length - 1
  // карточка под подсветкой, а если места снизу нет — над ней
  const below = rect ? rect.bottom + 180 < window.innerHeight : true
  const cardStyle: React.CSSProperties = rect
    ? {
        top: below ? rect.bottom + PAD + 10 : Math.max(12, rect.top - PAD - 190),
        left: Math.min(Math.max(12, rect.left - PAD), Math.max(12, window.innerWidth - 372)),
      }
    : { top: '50%', left: '50%', transform: 'translate(-50%, -50%)' }

  return (
    <div className="tour" role="dialog" aria-label={`Подсказка ${i + 1} из ${steps.length}`}>
      {rect ? (
        <div
          className="tour-hole"
          style={{
            top: rect.top - PAD,
            left: rect.left - PAD,
            width: rect.width + PAD * 2,
            height: rect.height + PAD * 2,
          }}
        />
      ) : (
        <div className="tour-dim" />
      )}

      <div className="tour-card" style={cardStyle}>
        <div className="tour-step">Шаг {i + 1} из {steps.length}</div>
        <h3>{step.title}</h3>
        <p>{step.text}</p>
        <div className="row spread mt">
          <button className="small ghost" onClick={onDone}>Пропустить</button>
          <div className="row">
            {i > 0 && <button className="small" onClick={() => setI(i - 1)}>Назад</button>}
            <button className="small primary" onClick={() => (last ? onDone() : setI(i + 1))}>
              {last ? 'Понятно, начать' : 'Далее'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
