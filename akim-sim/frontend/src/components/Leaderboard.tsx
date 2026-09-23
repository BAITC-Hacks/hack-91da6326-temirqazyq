import { useEffect, useMemo, useState } from 'react'
import { Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { api, type Compare, type Decision, type Entry, type Meta, type Oracle } from '../api'
import { VIZ, decisionLabel, signed } from '../lib'
import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Hint } from './Viz'

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
    api
      .compare({ decisions: a.decisions, event_id: a.event_id }, { decisions: b.decisions, event_id: b.event_id })
      .then(setCmp)
      .catch((e) => setErr(String(e)))
  }, [picked, entries])

  const submit = async () => {
    setBusy(true); setErr('')
    try {
      localStorage.setItem('akim.team', team)
      await onSubmit(team, note)
      await load()
    } catch (e) { setErr(String(e)) } finally { setBusy(false) }
  }
  const evTitle = (id: string | null) => (id ? meta.events.find((e) => e.id === id)?.title ?? id : 'базовый')
  const youAt = currentScore != null
    ? oracle?.histogram.find((h) => currentScore >= h.from && currentScore < h.to)?.from.toFixed(1)
    : undefined

  /* Колонки таблицы. Фильтры по миру и по наличию критических значений, сортировка
     по всем числовым столбцам — то, чего раньше не было совсем. */
  const columns = useMemo<ColumnsType<Entry>>(() => {
    const worlds = [{ text: 'базовый', value: 'base' }, ...meta.events.map((e) => ({ text: e.title, value: e.id }))]
    return [
      { title: '#', dataIndex: 'rank', width: 52, align: 'right', render: (v: number) => <span className="num">{v}</span> },
      {
        title: 'Команда', dataIndex: 'team', ellipsis: true,
        sorter: (a, b) => a.team.localeCompare(b.team, 'ru'),
        render: (v: string, r) => (
          <>
            <b>{v}</b>
            {r.note && <div className="tiny muted">{r.note}</div>}
          </>
        ),
      },
      {
        title: 'Мир', dataIndex: 'event_id', width: 150, filters: worlds,
        onFilter: (val, r) => (r.event_id ?? 'base') === val,
        render: (v: string | null) =>
          v ? <Tag color="red">{evTitle(v)}</Tag> : <Tag>базовый</Tag>,
      },
      {
        title: 'Score', dataIndex: 'score', width: 88, align: 'right',
        defaultSortOrder: 'descend', sorter: (a, b) => a.score - b.score,
        render: (v: number) => <b className="num">{v}</b>,
      },
      {
        title: 'Δ к базе', dataIndex: 'delta', width: 96, align: 'right',
        sorter: (a, b) => a.delta - b.delta,
        render: (v: number) => <span className={`num ${v >= 0 ? 'pos' : 'neg'}`}>{signed(v)}</span>,
      },
      {
        title: 'Стоимость', dataIndex: 'total_cost', width: 104, align: 'right',
        sorter: (a, b) => a.total_cost - b.total_cost,
        render: (v: number) => <span className="num">{v}</span>,
      },
      {
        title: 'Крит.', dataIndex: 'n_crit', width: 80, align: 'right',
        sorter: (a, b) => a.n_crit - b.n_crit,
        filters: [{ text: 'без критических', value: 'none' }, { text: 'есть критические', value: 'some' }],
        onFilter: (val, r) => (val === 'none' ? r.n_crit === 0 : r.n_crit > 0),
        render: (v: number) => <span className={`num ${v ? 'neg' : 'pos'}`}>{v}</span>,
      },
      {
        title: 'Мин. район', dataIndex: 'd_min', width: 110, align: 'right',
        sorter: (a, b) => a.d_min - b.d_min,
        render: (v: number) => <span className="num">{v.toFixed(1)}</span>,
      },
      {
        title: '', key: 'actions', width: 196, fixed: 'right', align: 'right',
        render: (_, r) => (
          <div className="row" style={{ flexWrap: 'nowrap', justifyContent: 'flex-end' }}>
            <button className="small" onClick={() => onLoad(r.decisions, r.event_id)}>Загрузить</button>
            <a href={api.reportUrl(r.id)} target="_blank" rel="noreferrer">
              <button className="small ghost">Отчёт</button>
            </a>
          </div>
        ),
      },
    ]
  }, [meta.events, onLoad])

  return (
    <div className="grid">
      <div className="grid two">
        <div className="panel">
          <h2>Отправить сценарий в лидерборд</h2>
          <p className="small muted">
            Score пересчитывается на сервере при отправке, поэтому подделать результат нельзя.
          </p>
          <div className="row mt">
            <input placeholder="Название команды" value={team} onChange={(e) => setTeam(e.target.value)} style={{ flex: 1 }} />
            <button className="primary" disabled={!canSubmit || !team.trim() || busy} onClick={submit}>
              {busy ? (
                <><span className="spinner" /> Отправляем…</>
              ) : (
                `Отправить${currentScore != null ? ` (${currentScore})` : ''}`
              )}
            </button>
          </div>
          <input
            className="mt"
            placeholder="Комментарий к сценарию (необязательно)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            style={{ width: '100%' }}
          />
          {!canSubmit && (
            <div className="notice info mt">
              <span className="ic">→</span>
              <span>Нужен рассчитанный Score валидного набора — вернитесь на вкладку «Решения».</span>
            </div>
          )}
          {err && <p className="error mt">{err}</p>}
        </div>

        <div className="panel">
          <h2>Где ваш результат среди всех возможных</h2>
          {oracle ? (
            <>
              <p className="small muted">
                <Hint term="oracle">Оракул</Hint> перебрал {oracle.n_valid.toLocaleString('ru')} допустимых наборов в
                мире «{evTitle(eventId)}». Максимум — {oracle.best_score}.
              </p>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={oracle.histogram.map((h) => ({ x: h.from.toFixed(1), n: h.count }))} margin={{ top: 8, right: 8, bottom: 18, left: 0 }}>
                  <CartesianGrid stroke={VIZ.grid} vertical={false} />
                  <XAxis
                    dataKey="x" stroke={VIZ.axis} tick={{ fontSize: 11 }} tickLine={false} interval={3}
                    label={{ value: 'Score', position: 'insideBottom', offset: -12, fill: VIZ.axis, fontSize: 11 }}
                  />
                  <YAxis
                    stroke={VIZ.axis} tick={{ fontSize: 11 }} tickLine={false} width={52}
                    tickFormatter={(v: number) => (v >= 1000 ? `${Math.round(v / 1000)}к` : String(v))}
                  />
                  <Tooltip
                    cursor={{ fill: '#ffffff0a' }}
                    formatter={(v: unknown) => [`${Number(v).toLocaleString('ru')} наборов`, 'В этом столбце']}
                    labelFormatter={(l) => `Score от ${l}`}
                  />
                  {youAt && (
                    <ReferenceLine
                      x={youAt} stroke={VIZ.axis} strokeWidth={1}
                      label={{ value: 'вы здесь', fill: '#f7f8f8', fontSize: 11, position: 'top' }}
                    />
                  )}
                  <Bar dataKey="n" fill={VIZ.after} radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
              <p className="tiny muted">
                <b><Hint term="pareto">Парето</Hint></b> (стоимость → лучший достижимый Score):{' '}
                {oracle.pareto.map((p) => `${p.cost}→${p.score}`).join(' · ')}
              </p>
            </>
          ) : (
            <p className="muted"><span className="spinner" /> Оракул перебирает наборы…</p>
          )}
        </div>
      </div>

      <div className="panel">
        <h2 className="mb">Лидерборд</h2>
        <Table<Entry>
          dataSource={entries}
          columns={columns}
          rowKey="id"
          size="small"
          pagination={entries.length > 12 ? { pageSize: 12, showSizeChanger: false } : false}
          scroll={{ x: 'max-content' }}
          locale={{ emptyText: 'Пока пусто — отправьте первый сценарий' }}
          expandable={{
            expandedRowRender: (r) => (
              <div className="small">
                <b>Пять решений:</b>
                <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                  {r.decisions.map((d, i) => <li key={i}>{decisionLabel(meta, d)}</li>)}
                </ul>
              </div>
            ),
            rowExpandable: () => true,
          }}
          rowSelection={{
            selectedRowKeys: picked,
            onChange: (keys) => setPicked(keys.slice(-2) as number[]),
            hideSelectAll: true,
            getCheckboxProps: (r) => ({
              disabled: picked.length >= 2 && !picked.includes(r.id),
              name: r.team,
            }),
          }}
        />
      </div>

      {cmp && picked.length === 2 && (
        <div className="panel">
          <h2>
            Сравнение: {entries.find((e) => e.id === picked[0])?.team} (A) против{' '}
            {entries.find((e) => e.id === picked[1])?.team} (B) · разница Score{' '}
            <span className={cmp.score_diff >= 0 ? 'pos' : 'neg'}>{signed(cmp.score_diff)}</span>
          </h2>
          <div className="grid two mt">
            <table>
              <thead><tr><th>Метрика</th><th className="num">A</th><th className="num">B</th></tr></thead>
              <tbody>
                <tr><td>Score</td><td className="num">{cmp.a.score}</td><td className="num">{cmp.b.score}</td></tr>
                <tr><td>Стоимость</td><td className="num">{cmp.a.cost}</td><td className="num">{cmp.b.cost}</td></tr>
                <tr><td>Средний балл районов</td><td className="num">{cmp.a.d_avg.toFixed(2)}</td><td className="num">{cmp.b.d_avg.toFixed(2)}</td></tr>
                <tr><td>Слабейший район</td><td className="num">{cmp.a.d_min.toFixed(2)}</td><td className="num">{cmp.b.d_min.toFixed(2)}</td></tr>
                <tr><td>Критических ячеек</td><td className="num">{cmp.a.n_crit}</td><td className="num">{cmp.b.n_crit}</td></tr>
                {cmp.per_district.map((d) => (
                  <tr key={d.district_id}>
                    <td className="muted">{d.name}</td>
                    <td className="num">{d.a.toFixed(1)}</td>
                    <td className={`num ${d.diff >= 0 ? 'pos' : 'neg'}`}>{d.b.toFixed(1)} ({signed(d.diff, 1)})</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div>
              <h3>Только в A</h3>
              <ul className="small">{cmp.only_a.map((d, i) => <li key={i}>{decisionLabel(meta, d)}</li>)}{!cmp.only_a.length && <li className="muted">—</li>}</ul>
              <h3>Только в B</h3>
              <ul className="small">{cmp.only_b.map((d, i) => <li key={i}>{decisionLabel(meta, d)}</li>)}{!cmp.only_b.length && <li className="muted">—</li>}</ul>
              <h3>Различающиеся показатели</h3>
              <p className="tiny muted">
                {cmp.per_indicator.map((p) => `${p.district} ${p.code}: ${p.a.toFixed(1)}→${p.b.toFixed(1)}`).join(' · ') || '—'}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
