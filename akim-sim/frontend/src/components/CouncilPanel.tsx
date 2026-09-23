import type { Council } from '../api'
import { Hint } from './Viz'

const ICON: Record<string, string> = { ecologist: '🌳', transport: '🚌', finance: '💼', nura: '🏘️' }

export default function CouncilPanel({
  council,
  loading,
  onConvene,
  canConvene,
}: {
  council: Council | null
  loading: boolean
  onConvene: () => void
  canConvene: boolean
}) {
  return (
    <div className="panel">
      <div className="row spread mb">
        <div>
          <h2>Совет депутатов</h2>
          <div className="small muted">
            Четыре персоны с разными ценностями оценивают ваш сценарий по 10-балльной шкале и спорят. Модератор
            подводит итог. Это способ увидеть компромиссы плана чужими глазами.
          </div>
        </div>
        <button className="primary" onClick={onConvene} disabled={!canConvene || loading}>
          {loading ? <><span className="spinner" /> Депутаты совещаются…</> : council ? 'Созвать заново' : 'Созвать совет'}
        </button>
      </div>

      {!canConvene && (
        <div className="notice info">
          <span className="ic">→</span>
          <span>Сначала соберите валидный набор и рассчитайте Score на вкладке «Решения».</span>
        </div>
      )}

      {council && (
        <>
          <div className="row mb">
            {council._mode === 'llm' ? (
              <span className="badge on">LLM</span>
            ) : (
              <span className="badge warn"><Hint term="fallback">шаблонный режим</Hint></span>
            )}
          </div>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }}>
            {council.speeches.map((s) => (
              <div className="persona" key={s.persona_id}>
                <div className="head">
                  <b>{ICON[s.persona_id] ?? '👤'} {s.persona}</b>
                  <span className="score">
                    {s.score}<span className="tiny muted">/10</span>
                  </span>
                </div>
                <div className="tiny muted mb">{council.personas.find((p) => p.id === s.persona_id)?.stance}</div>
                <div>{s.statement}</div>
                <div className="demand">Требование: {s.demand}</div>
              </div>
            ))}
          </div>
          <div className="mt grid three">
            <div className="ai-card"><h3>В чём согласились</h3><p>{council.moderator.consensus}</p></div>
            <div className="ai-card"><h3>В чём разошлись</h3><p>{council.moderator.conflict}</p></div>
            <div className="ai-card"><h3>Вердикт модератора</h3><p>{council.moderator.verdict}</p></div>
          </div>
        </>
      )}
    </div>
  )
}
