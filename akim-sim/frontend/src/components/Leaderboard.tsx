import { useEffect, useState } from 'react'
import { api, type Compare, type Decision, type Entry, type Meta, type Oracle } from '../api'
import { decisionLabel, signed } from '../lib'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, ReferenceLine } from 'recharts'

type Props = {
  meta: Meta
  eventId: string | null
  canSubmit: boolean
  currentScore: number | null
  onSubmit: (team: string, note: string) => Promise<void>
  onLoad: (d: Decision[], eventId: string | null) => void
  refreshKey: number
}

export default function Leaderboard({ meta, eventId, canSubmit, currentScore, onSubmit, onLoad, refreshKey }: Props) {
  const [team, setTeam] = useState(() => localStorage.getItem('akim.team') ?? '')
  const [note, setNote] = useState('')
  const [entries, setEntries] = useState<Entry[]>([])
  const [picked, setPicked] = useState<number[]>([])
  const [cmp, setCmp] = useState<Compare | null>(null)
  const [oracle, setOracle] = useState<Oracle | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const load = () => api.leaderboard().then(setEntries).catch((e) => setErr(String(e)))
  useEffect(() => { load() }, [refreshKey])
  useEffect(() => { api.oracle(eventId).then(setOracle).catch(() => setOracle(null)) }, [eventId])

  useEffect(() => {
    if (picked.length !== 2) { setCmp(null); return }
    const [a, b] = picked.map((id) => entries.find((e) => e.id === id)!)
    api.compare({ decisions: a.decisions, event_id: a.event_id }, { decisions: b.decisions, event_id: b.event_id }).then(setCmp).catch((e) => setErr(String(e)))
  }, [picked, entries])

  const submit = async () => {
    setBusy(true); setErr('')
    try { localStorage.setItem('akim.team', team); await onSubmit(team, note); await load() } catch (e) { setErr(String(e)) } finally { setBusy(false) }
  }
  const toggle = (id: number) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id].slice(-2)))
  const evTitle = (id: string | null) => (id ? meta.events.find((e) => e.id === id)?.title ?? id : 'базовый')

  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="grid two">
        <div className="panel">
          <h2>Отправить сценарий в лидерборд</h2>
          <div className="row mt">
            <input placeholder="Название команды" value={team} onChange={(e) => setTeam(e.target.value)} style={{ flex: 1 }} />
            <button className="primary" disabled={!canSubmit || !team.trim() || busy} onClick={submit}>{busy ? <span className="spinner" /> : `Отправить${currentScore != null ? ` (${currentScore})` : ''}`}</button>
          </div>
          <input className="mt" placeholder="Комментарий к сценарию (необязательно)" value={note} onChange={(e) => setNote(e.target.value)} style={{ width: '100%' }} />
          {!canSubmit && <p className="small muted mt">Нужен рассчитанный Score валидного набора.</p>}
          {err && <p className="error mt">{err}</p>}
        </div>
        <div className="panel">
          <h2>Оракул: распределение всех допустимых наборов</h2>
          {oracle ? (
            <>
              <div className="small muted mb">{oracle.n_valid.toLocaleString('ru')} наборов · максимум {oracle.best_score} · мир: {evTitle(eventId)}</div>
              <ResponsiveContainer width="100%" height={150}>
                <BarChart data={oracle.histogram.map((h) => ({ x: h.from.toFixed(1), n: h.count }))}>
                  <CartesianGrid stroke="#2e3a55" vertical={false} />
                  <XAxis dataKey="x" stroke="#94a0b8" tick={{ fontSize: 10 }} interval={3} />
                  <YAxis stroke="#94a0b8" tick={{ fontSize: 10 }} width={40} />
                  <Tooltip />
                  {currentScore != null && <ReferenceLine x={oracle.histogram.find((h) => currentScore >= h.from && currentScore < h.to)?.from.toFixed(1)} stroke="#f5b041" label={{ value: 'вы', fill: '#f5b041', fontSize: 11 }} />}
                  <Bar dataKey="n" fill="#4cc2ff" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
              <div className="small muted">Парето (стоимость → лучший Score): {oracle.pareto.map((p) => `${p.cost}→${p.score}`).join(' · ')}</div>
            </>
          ) : <span className="spinner" />}
        </div>
      </div>

      <div className="panel">
        <div className="row spread mb">
          <h2>Лидерборд</h2>
          <span className="small muted">Кликните на две строки, чтобы сравнить. Отчёт — одностраничная презентация сценария.</span>
        </div>
        <table>
          <thead><tr><th>#</th><th>Команда</th><th>Мир</th><th className="num">Score</th><th className="num">Δ к базе</th><th className="num">Стоимость</th><th className="num">Крит.</th><th className="num">Мин. район</th><th>Решения</th><th></th></tr></thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id} className={`clickable ${picked.includes(e.id) ? 'picked' : ''}`} onClick={() => toggle(e.id)}>
                <td>{e.rank}</td><td><b>{e.team}</b>{e.note && <div className="small muted">{e.note}</div>}</td><td className="small">{evTitle(e.event_id)}</td>
                <td className="num"><b>{e.score}</b></td><td className={`num ${e.delta >= 0 ? 'pos' : 'neg'}`}>{signed(e.delta)}</td><td className="num">{e.total_cost}</td><td className="num">{e.n_crit}</td><td className="num">{e.d_min.toFixed(1)}</td>
                <td className="small muted">{e.decisions.map((d) => `${d.measure_id}${d.district_id ? '/' + d.district_id : ''}`).join(', ')}</td>
                <td className="row" onClick={(ev) => ev.stopPropagation()}>
                  <button className="small" onClick={() => onLoad(e.decisions, e.event_id)}>Загрузить</button>
                  <a className="small" href={api.reportUrl(e.id)} target="_blank" rel="noreferrer"><button className="small">Отчёт</button></a>
                </td>
              </tr>
            ))}
            {!entries.length && <tr><td colSpan={10} className="muted">Пока пусто — отправьте первый сценарий.</td></tr>}
          </tbody>
        </table>
      </div>

      {cmp && picked.length === 2 && (
        <div className="panel">
          <h2>Сравнение: {entries.find((e) => e.id === picked[0])?.team} (A) vs {entries.find((e) => e.id === picked[1])?.team} (B) · разница Score <span className={cmp.score_diff >= 0 ? 'pos' : 'neg'}>{signed(cmp.score_diff)}</span></h2>
          <div className="grid two mt">
            <div>
              <table>
                <thead><tr><th>Метрика</th><th className="num">A</th><th className="num">B</th></tr></thead>
                <tbody>
                  <tr><td>Score</td><td className="num">{cmp.a.score}</td><td className="num">{cmp.b.score}</td></tr>
                  <tr><td>Стоимость</td><td className="num">{cmp.a.cost}</td><td className="num">{cmp.b.cost}</td></tr>
                  <tr><td>Средний балл районов</td><td className="num">{cmp.a.d_avg.toFixed(2)}</td><td className="num">{cmp.b.d_avg.toFixed(2)}</td></tr>
                  <tr><td>Слабейший район</td><td className="num">{cmp.a.d_min.toFixed(2)}</td><td className="num">{cmp.b.d_min.toFixed(2)}</td></tr>
                  <tr><td>Критических</td><td className="num">{cmp.a.n_crit}</td><td className="num">{cmp.b.n_crit}</td></tr>
                  {cmp.per_district.map((d) => <tr key={d.district_id}><td className="muted">{d.name}</td><td className="num">{d.a.toFixed(1)}</td><td className={`num ${d.diff >= 0 ? 'pos' : 'neg'}`}>{d.b.toFixed(1)} ({signed(d.diff, 1)})</td></tr>)}
                </tbody>
              </table>
            </div>
            <div>
              <h3>Только в A</h3><ul>{cmp.only_a.map((d, i) => <li key={i}>{decisionLabel(meta, d)}</li>)}{!cmp.only_a.length && <li className="muted">—</li>}</ul>
              <h3>Только в B</h3><ul>{cmp.only_b.map((d, i) => <li key={i}>{decisionLabel(meta, d)}</li>)}{!cmp.only_b.length && <li className="muted">—</li>}</ul>
              <h3>Различающиеся показатели</h3>
              <div className="small muted">{cmp.per_indicator.map((p) => `${p.district} ${p.code}: ${p.a.toFixed(1)}→${p.b.toFixed(1)}`).join(' · ') || '—'}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
