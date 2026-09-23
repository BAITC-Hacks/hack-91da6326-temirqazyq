import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Analysis, type Council, type CustomEvent, type Decision, type EventOut, type Meta, type Oracle, type ScoreResult, type ValidationResult, type World } from './api'
import Planner from './components/Planner'
import Results from './components/Results'
import AIPanel from './components/AIPanel'
import CouncilPanel from './components/CouncilPanel'
import EventPanel from './components/EventPanel'
import Leaderboard from './components/Leaderboard'
import Onboarding from './components/Onboarding'
import SideNav, { type NavStep } from './components/SideNav'
import Tour from './components/Tour'
import { PLANNER_TOUR } from './components/tourSteps'
import { EXAMPLE_DECISIONS, plural } from './lib'

type Tab = 'plan' | 'result' | 'council' | 'event' | 'board'

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
  const [oracle, setOracle] = useState<Oracle | null>(null)
  const [showIntro, setShowIntro] = useState(() => localStorage.getItem('akim.intro') !== 'done')
  const [tourOn, setTourOn] = useState(false)
  const [custom, setCustom] = useState<CustomEvent | null>(null)
  const [customError, setCustomError] = useState('')
  const scoredFor = useRef<string>('')

  const setB = (k: string, v: boolean) => setBusy((b) => ({ ...b, [k]: v }))
  const key = (d: Decision[], e: string | null) => JSON.stringify([d, e])

  useEffect(() => { api.meta().then(setMeta).catch((e) => setError(String(e))) }, [])

  // лучший возможный Score — ориентир «докуда вообще можно дойти», нужен и во вступлении, и в планировщике
  useEffect(() => { api.oracle(eventId).then(setOracle).catch(() => setOracle(null)) }, [eventId])

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

  const runCustom = async (text: string) => {
    setB('custom', true); setCustomError(''); setCustom(null)
    try {
      setCustom(await api.customEvent(decisions, eventId, text))
    } catch (e) {
      setCustomError(String(e).replace(/^Error:\s*/, ''))
    } finally { setB('custom', false) }
  }

  const submit = async (team: string, note: string) => {
    await api.submit(team, decisions, eventId, analysis, note)
    setBoardKey((k) => k + 1)
  }

  const loadScenario = (d: Decision[], e: string | null) => { setEventId(e); setDecisions(d); setTab('plan') }
  const closeIntro = () => { localStorage.setItem('akim.intro', 'done'); setShowIntro(false) }
  const startTour = () => { setTab('plan'); setShowIntro(false); localStorage.setItem('akim.intro', 'done'); setTourOn(true) }
  const applyDecisions = (d: Decision[]) => { setDecisions(d); setTab('plan') }

  if (!meta) return <div className="app"><p className="muted">{error || 'Загрузка датасета…'}</p></div>
  const hasResult = !!result && scoredFor.current === key(decisions, eventId)
  const planReady = !!validation?.valid
  const needPlan = 'Сначала соберите валидный план'
  const needScore = 'Сначала рассчитайте результат'

  const NAV: NavStep[] = [
    {
      id: 'plan', label: 'Решения', done: planReady,
      hint: `Выберите ${meta.rules.decisions_required} ${plural(meta.rules.decisions_required, 'мероприятие', 'мероприятия', 'мероприятий')} в пределах бюджета`,
      badge: <span className="nav-count">{decisions.length}/{meta.rules.decisions_required}</span>,
    },
    {
      id: 'result', label: 'Результат и разбор AI', done: hasResult,
      hint: 'Оценка города, что изменилось и мнение трёх агентов',
      locked: hasResult ? undefined : planReady ? 'Нажмите «Рассчитать результат»' : needPlan,
    },
    {
      id: 'council', label: 'Совет депутатов',
      hint: 'Четыре взгляда на ваш план и вердикт модератора',
      locked: hasResult ? undefined : needScore,
    },
    {
      id: 'event', label: 'Чёрный лебедь',
      hint: 'Кризис: готовый сценарий или своя проблема словами',
      locked: planReady ? undefined : needPlan,
    },
    {
      id: 'board', label: 'Лидерборд',
      hint: 'Сравнение с другими командами и отчёт',
      locked: hasResult ? undefined : needScore,
    },
  ]

  return (
    <div className="app">
      {showIntro && (
        <Onboarding
          meta={meta}
          bestScore={oracle?.best_score ?? null}
          onStart={startTour}
          onExample={() => { setDecisions(EXAMPLE_DECISIONS); setTab('plan'); closeIntro() }}
        />
      )}
      {tourOn && <Tour steps={PLANNER_TOUR} onDone={() => setTourOn(false)} />}
      <header className="topbar">
        <h1>Аким на 5 часов</h1>
        {/* Бейдж события оставлен: он не справочный, а про состояние — предупреждает,
            что расчёты идут в мире после катастрофы, а не в базовом. */}
        {eventId && (
          <span className="badge event">
            ⚡ {meta.events.find((e) => e.id === eventId)?.title}
          </span>
        )}
        <div className="topbar-actions">
          <button
            className="small ghost"
            onClick={() => {
              setTab('plan');
              setTourOn(true);
            }}
          >
            Показать, как пользоваться
          </button>
          <button
            className="help"
            title="Что это за симулятор"
            aria-label="Что это за симулятор"
            onClick={() => setShowIntro(true)}
          >
            ?
          </button>
        </div>
      </header>

      {error && (
        <div className="notice bad mb">
          <span className="ic">!</span>
          <span style={{ flex: 1 }}>{error}</span>
          <button className="small ghost" onClick={() => setError('')} aria-label="Скрыть ошибку">✕</button>
        </div>
      )}

      <div className="shell">
        <SideNav steps={NAV} active={tab} onPick={(id) => setTab(id as Tab)} />
        <main className="stage">
      {tab === 'plan' && (
        <Planner
          meta={meta} world={world} decisions={decisions} validation={validation}
          busy={!!busy.score} onChange={setDecisions} onScore={runScore} bestScore={oracle?.best_score ?? null}
        />
      )}

      {tab === 'result' &&
        (hasResult ? (
          <div className="grid">
            <Results meta={meta} result={result!} analysis={analysis} />
            <AIPanel meta={meta} analysis={analysis} loading={!!busy.ai} onApply={applyDecisions} />
            <div className="next-steps">
              <b>Что дальше</b>
              <button onClick={() => setTab('council')}>Созвать совет депутатов →</button>
              <button onClick={() => setTab('event')}>Испытать кризисом →</button>
              <button onClick={() => setTab('board')}>Сравниться с другими →</button>
            </div>
          </div>
        ) : (
          <div className="panel center-empty">
            <h2>Результата пока нет</h2>
            <p className="muted">
              Соберите набор из {meta.rules.decisions_required} решений в пределах бюджета и нажмите «Рассчитать
              результат» — сюда придут Score, графики и разбор от трёх AI-агентов.
            </p>
            <button className="primary mt" onClick={() => setTab('plan')}>К решениям</button>
          </div>
        ))}

      {tab === 'council' && (
        <CouncilPanel council={council} loading={!!busy.council} onConvene={convene} canConvene={hasResult} />
      )}

      {tab === 'event' && (
        <EventPanel
          meta={meta} event={event} activeEventId={eventId} loading={!!busy.event} hasPlan={!!validation?.valid}
          onTrigger={trigger}
          onEnterWorld={() => { if (event) { setEventId(event.event.id); setTab('plan') } }}
          onReset={() => { setEventId(null); setEvent(null); setCustom(null) }}
          custom={custom}
          customBusy={!!busy.custom}
          customError={customError}
          onCustom={runCustom}
        />
      )}

      {tab === 'board' && (
        <Leaderboard
          meta={meta} eventId={eventId} canSubmit={hasResult}
          currentScore={hasResult ? result!.score : null}
          onSubmit={submit} onLoad={loadScenario} refreshKey={boardKey}
        />
      )}

        </main>
      </div>

      <footer className="small muted app-footer">
        Все числа считает детерминированный движок и покрывают тесты. AI получает готовую трассу
        расчёта и только объясняет, критикует и советует.
      </footer>
    </div>
  )
}
