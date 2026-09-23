import type { Analysis, Decision, Meta } from '../api'
import { signed } from '../lib'

function ModeBadge({ mode, llm }: { mode?: string; llm?: Analysis['llm'] }) {
  if (!mode) return null
  return mode === 'llm'
    ? <span className="badge on">LLM · {llm?.model}</span>
    : <span className="badge warn" title="Ключ LLM не задан или запрос упал — используется шаблонное объяснение на основе трассы движка">шаблонный режим</span>
}

export default function AIPanel({ analysis, loading, onApply }: { meta: Meta; analysis: Analysis | null; loading: boolean; onApply: (d: Decision[]) => void }) {
  if (loading && !analysis) return <div className="panel"><span className="spinner" /> Аналитик, критик и советник изучают сценарий…</div>
  if (!analysis) return null
  const { analyst, critic, advisor } = analysis
  return (
    <div className="grid three">
      <div className="ai-card">
        <h2>🧠 Аналитик <ModeBadge mode={analyst?._mode} llm={analysis.llm} /></h2>
        {analyst && (
          <>
            <p><b>{analyst.headline}</b></p>
            <p className="muted">{analyst.summary}</p>
            <h3>Сильные стороны</h3><ul>{analyst.strengths.map((s, i) => <li key={i}>{s}</li>)}</ul>
            <h3>Риски</h3><ul>{analyst.risks.map((s, i) => <li key={i}>{s}</li>)}</ul>
            <h3>Компромиссы</h3><ul>{analyst.tradeoffs.map((s, i) => <li key={i}>{s}</li>)}</ul>
            {analyst.resident_voice && <div className="quote mt"><b>{analyst.resident_voice.district}:</b> «{analyst.resident_voice.quote}»</div>}
          </>
        )}
      </div>
      <div className="ai-card">
        <h2>🔍 Критик <ModeBadge mode={critic?._mode} llm={analysis.llm} /></h2>
        {critic && (
          <>
            <p><b>{critic.verdict}</b></p>
            <ul>
              {critic.weaknesses.map((w, i) => <li key={i}><span className={`sev-${w.severity}`}>●</span> <b>{w.title}</b> — {w.detail}</li>)}
              {!critic.weaknesses.length && <li className="muted">Слабых мест не найдено.</li>}
            </ul>
            <h3>Вопросы команде</h3><ul>{critic.questions_to_team.map((q, i) => <li key={i}>{q}</li>)}</ul>
          </>
        )}
      </div>
      <div className="ai-card">
        <h2>🎯 Советник <ModeBadge mode={advisor?._mode} llm={analysis.llm} /></h2>
        {advisor && (
          <>
            {advisor.tool_calls?.length > 0 && <div className="small muted mb">Вызовы инструментов движка: {advisor.tool_calls.map((t) => t.name).join(' → ')}</div>}
            {advisor.recommendations.map((r, i) => (
              <div className="rec" key={i}>
                <div className="row spread">
                  <b>{r.title}</b>
                  {r.verified ? <b className="score">{r.new_score} <span className="small pos">({signed(r.gain)})</span></b> : <span className="small error">не прошло валидацию</span>}
                </div>
                <div className="small muted">{r.change} · стоимость {r.cost}</div>
                <div className="small mt" style={{ marginTop: 6 }}>{r.rationale}{r.invalid_reason && <span className="error"> {r.invalid_reason}</span>}</div>
                {r.verified && r.decisions?.length === 5 && <button className="small mt" onClick={() => onApply(r.decisions)}>Применить набор</button>}
              </div>
            ))}
            {!advisor.recommendations.length && <p className="muted">Улучшений одной заменой не найдено — вы близки к оптимуму.</p>}
            <p className="small muted mt">{advisor.keep_as_is_argument}</p>
          </>
        )}
        {analysis.oracle && (
          <div className="mt small">
            <h3>Оракул (полный перебор)</h3>
            <div>Лучший допустимый набор — <b>{analysis.oracle.best_score}</b>:</div>
            <ul>{analysis.oracle.best_set.map((s, i) => <li key={i}>{s}</li>)}</ul>
          </div>
        )}
      </div>
    </div>
  )
}
