import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Analysis, type Council, type Decision, type EventOut, type Meta, type ScoreResult, type ValidationResult, type World } from './api'
import Planner from './components/Planner'
import Results from './components/Results'
import AIPanel from './components/AIPanel'
import CouncilPanel from './components/CouncilPanel'
import EventPanel from './components/EventPanel'
import Leaderboard from './components/Leaderboard'

type Tab = 'plan' | 'result' | 'council' | 'event' | 'board'
const TABS: { id: Tab; label: string }[] = [
  { id: 'plan', label: '1 · Решения' },
  { id: 'result', label: '2 · Результат и AI' },
  { id: 'council', label: '3 · Совет' },
  { id: 'event', label: '4 · Событие' },
  { id: 'board', label: '5 · Лидерборд' },
]

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [tab, setTab] = useState<Tab>('plan')
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [eventId, setEventId] = useState<string | null>(null)
  const [world, setWorld] = useState<World | null>(null)
  const [validation, setValidation] = useState<ValidationResult | null>(null)
  const [result, setResult] = useState<ScoreResult | null>(null)
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [council, setCouncil] = useState<Council | null>(null)
  const [event, setEvent] = useState<EventOut | null>(null)
  const [busy, setBusy] = useState<Record<string, boolean>>({})
  const [error, setError] = useState('')
  const [boardKey, setBoardKey] = useState(0)
  const scoredFor = useRef<string>('')

  const setB = (k: string, v: boolean) => setBusy((b) => ({ ...b, [k]: v }))
  const key = (d: Decision[], e: string | null) => JSON.stringify([d, e])

  useEffect(() => { api.meta().then(setMeta).catch((e) => setError(String(e))) }, [])

  // живая валидация при каждом изменении набора / мира
  useEffect(() => {
    if (!meta) return
    const t = setTimeout(() => {
      api.score(decisions, eventId).then((r) => { setValidation(r.validation); setWorld(r.world) }).catch((e) => setError(String(e)))
    }, 120)
    return () => clearTimeout(t)
  }, [decisions, eventId, meta])

  // результат устаревает при изменении набора
  useEffect(() => {
    if (scoredFor.current !== key(decisions, eventId)) { setResult(null); setAnalysis(null); setCouncil(null) }
  }, [decisions, eventId])

  const runScore = useCallback(async () => {
    setB('score', true); setError('')
    try {
      const r = await api.score(decisions, eventId)
      if (!r.result) { setValidation(r.validation); return }
      setResult(r.result); scoredFor.current = key(decisions, eventId); setTab('result')
      setB('ai', true)
      api.analyze(decisions, eventId).then(setAnalysis).catch((e) => setError(String(e))).finally(() => setB('ai', false))
    } catch (e) { setError(String(e)) } finally { setB('score', false) }
  }, [decisions, eventId])

  const convene = async () => {
    setB('council', true); setError('')
    try { setCouncil(await api.council(decisions, eventId)) } catch (e) { setError(String(e)) } finally { setB('council', false) }
  }

  const trigger = async (id: string | null) => {
    setB('event', true); setError('')
    try { setEvent(await api.triggerEvent(decisions, eventId, id, event ? [event.event.id] : [])) } catch (e) { setError(String(e)) } finally { setB('event', false) }
  }

  const submit = async (team: string, note: string) => {
    await api.submit(team, decisions, eventId, analysis, note)
    setBoardKey((k) => k + 1)
  }

  const loadScenario = (d: Decision[], e: string | null) => { setEventId(e); setDecisions(d); setTab('plan') }
  const applyDecisions = (d: Decision[]) => { setDecisions(d); setTab('plan') }

  if (!meta) return <div className="app"><p className="muted">{error || 'Загрузка датасета…'}</p></div>
  const hasResult = !!result && scoredFor.current === key(decisions, eventId)

  return (
    <div className="app">
      <header className="topbar">
        <div className="title">
          <h1>Аким на 5 часов</h1>
          <span>AI-симулятор управления городом · бюджет {world?.budget ?? meta.rules.budget} · горизонт {meta.rules.horizon_quarters} кварталов · база {meta.base_score}</span>
        </div>
        {eventId && <span className="badge event">⚡ {meta.events.find((e) => e.id === eventId)?.title}</span>}
        {meta.llm.enabled ? <span className="badge on">LLM: {meta.llm.provider} / {meta.llm.model}</span> : <span className="badge warn" title="Задайте LLM_PROVIDER и LLM_API_KEY в .env">LLM не подключён · шаблонный режим</span>}
        <nav className="tabs">
          {TABS.map((t) => (
            <button key={t.id} className={tab === t.id ? 'active' : ''} onClick={() => setTab(t.id)}>
              {t.label}{t.id === 'result' && hasResult && <span className="dot" />}
            </button>
          ))}
        </nav>
      </header>

      {error && <div className="issue mb">{error} <button className="small ghost" onClick={() => setError('')}>×</button></div>}

      {tab === 'plan' && <Planner meta={meta} world={world} decisions={decisions} validation={validation} busy={!!busy.score} onChange={setDecisions} onScore={runScore} />}

      {tab === 'result' && (hasResult ? (
        <div className="grid" style={{ gap: 16 }}>
          <Results meta={meta} result={result!} analysis={analysis} />
          <AIPanel meta={meta} analysis={analysis} loading={!!busy.ai} onApply={applyDecisions} />
          <div className="row">
            <button onClick={() => setTab('council')}>Созвать совет →</button>
            <button onClick={() => setTab('event')}>Испытать событием →</button>
            <button onClick={() => setTab('board')}>В лидерборд →</button>
          </div>
        </div>
      ) : <div className="panel"><p className="muted">Соберите валидный набор из 5 решений и нажмите «Рассчитать».</p><button onClick={() => setTab('plan')}>К решениям</button></div>)}

      {tab === 'council' && <CouncilPanel council={council} loading={!!busy.council} onConvene={convene} canConvene={hasResult} />}

      {tab === 'event' && (
        <EventPanel
          meta={meta} event={event} activeEventId={eventId} loading={!!busy.event} hasPlan={!!validation?.valid}
          onTrigger={trigger}
          onEnterWorld={() => { if (event) { setEventId(event.event.id); setTab('plan') } }}
          onReset={() => { setEventId(null); setEvent(null) }}
        />
      )}

      {tab === 'board' && (
        <Leaderboard meta={meta} eventId={eventId} canSubmit={hasResult} currentScore={hasResult ? result!.score : null} onSubmit={submit} onLoad={loadScenario} refreshKey={boardKey} />
      )}

      <footer className="small muted mt" style={{ marginTop: 32 }}>
        Формула: {meta.rules.formula}. Все числа считает детерминированный движок; LLM только объясняет, критикует и советует.
      </footer>
    </div>
  )
}
