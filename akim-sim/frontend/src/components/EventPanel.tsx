import { useState } from 'react'
import type { EventOut, Meta } from '../api'
import { districtName, signed } from '../lib'

type Props = {
  meta: Meta
  event: EventOut | null
  activeEventId: string | null
  loading: boolean
  hasPlan: boolean
  onTrigger: (id: string | null) => void
  onEnterWorld: () => void
  onReset: () => void
}

export default function EventPanel({ meta, event, activeEventId, loading, hasPlan, onTrigger, onEnterWorld, onReset }: Props) {
  const [choice, setChoice] = useState<string>('')
  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="panel">
        <div className="row spread">
          <div>
            <h2>«Чёрный лебедь»</h2>
            <div className="small muted">Неожиданное городское событие меняет исходные показатели, блокирует меры или режет бюджет. Ваш план пересчитывается в новом мире, и его нужно перераспределить.</div>
          </div>
          <div className="row">
            <select value={choice} onChange={(e) => setChoice(e.target.value)}>
              <option value="">Случайное событие</option>
              {meta.events.map((e) => <option key={e.id} value={e.id}>{e.title}</option>)}
            </select>
            <button className="primary" disabled={!hasPlan || loading} onClick={() => onTrigger(choice || null)}>{loading ? <span className="spinner" /> : 'Запустить событие'}</button>
            {activeEventId && <button className="ghost" onClick={onReset}>Вернуться в базовый мир</button>}
          </div>
        </div>
        {!hasPlan && <p className="muted mt">Сначала соберите валидный набор из 5 решений — событие покажет, как он «просядет».</p>}
        {activeEventId && <p className="mt"><span className="badge event">Активный мир: {meta.events.find((e) => e.id === activeEventId)?.title}</span> <span className="small muted">— все расчёты, лидерборд и AI-анализ идут в этом мире.</span></p>}
      </div>

      {event && (
        <div className="grid two">
          <div className="panel event-card">
            <h2>🚨 {event.event.title}</h2>
            <p>{event.narration.briefing}</p>
            <p className="muted">{event.narration.impact_summary}</p>
            <h3>Что советует ИИ</h3>
            <ul>{event.narration.advice.map((a, i) => <li key={i}>{a}</li>)}</ul>
            <div className="small muted">{event.narration._mode === 'llm' ? 'Нарратив: LLM' : 'Нарратив: шаблонный режим'}</div>
          </div>
          <div className="panel">
            <h2>Механика события</h2>
            <table>
              <tbody>
                {event.event.shocks.map((s, i) => <tr key={i}><td>Шок</td><td>{districtName(meta, s.district)} · {s.indicator}</td><td className={`num ${s.delta < 0 ? 'neg' : 'pos'}`}>{signed(s.delta, 0)}</td></tr>)}
                {event.event.blocked_measures.length > 0 && <tr><td>Заблокировано</td><td colSpan={2}>{event.event.blocked_measures.join(', ')}</td></tr>}
                {event.event.budget_delta !== 0 && <tr><td>Бюджет</td><td colSpan={2} className="neg">{signed(event.event.budget_delta, 0)} → {event.world.budget}</td></tr>}
                <tr><td>Score плана до события</td><td colSpan={2} className="num">{event.score_before ?? '—'}</td></tr>
                <tr><td>Score плана после (если ничего не менять)</td><td colSpan={2} className={`num ${event.score_before != null && event.score_after_if_unchanged < event.score_before ? 'neg' : ''}`}>{event.score_after_if_unchanged}</td></tr>
                <tr><td>База нового мира</td><td colSpan={2} className="num">{event.base_score_after}</td></tr>
                <tr><td>План всё ещё валиден?</td><td colSpan={2}>{event.plan_still_valid ? <span className="pos">да</span> : <span className="neg">нет: {event.validation.issues.map((i) => i.message).join('; ')}</span>}</td></tr>
              </tbody>
            </table>
            <button className="primary mt" onClick={onEnterWorld} disabled={activeEventId === event.event.id}>Перепланировать в этом мире →</button>
          </div>
        </div>
      )}
    </div>
  )
}
