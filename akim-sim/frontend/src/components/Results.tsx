import { Bar, BarChart, CartesianGrid, Cell, Legend, PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Analysis, Meta, ScoreResult } from '../api'
import { DIR_HEX, districtName, signed } from '../lib'

const GRID = '#2e3a55'
const TXT = '#94a0b8'

export default function Results({ meta, result, analysis }: { meta: Meta; result: ScoreResult; analysis: Analysis | null }) {
  const oracle = analysis?.oracle
  const districtData = result.districts.map((d) => ({ name: d.name, 'До': +d.score_before.toFixed(2), 'После': +d.score_after.toFixed(2) }))
  const measureData = result.measures.map((m) => ({ name: `${m.measure_id} ${m.district_id ? districtName(meta, m.district_id) : 'город'}`, 'Вклад': m.marginal_score, dir: meta.measures.find((x) => x.id === m.measure_id)!.direction, cost: m.cost }))
  const dirData = result.directions.map((d) => ({ name: d.name.split(' ')[0], 'До': d.before, 'После': d.after }))

  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="grid kpis">
        <div className="kpi hero"><b>{result.score}</b><span>Astana Quality of Life Score · база {result.base_score} (<span className={result.delta >= 0 ? 'pos' : 'neg'}>{signed(result.delta)}</span>)</span></div>
        <div className="kpi"><b>{result.total_cost}<span style={{ fontSize: 14 }}> / {result.budget}</span></b><span>Потрачено · остаток {result.remaining}</span></div>
        <div className="kpi"><b>{result.d_avg.toFixed(2)}</b><span>Средний балл районов (70%) · было {result.base_d_avg.toFixed(2)}</span></div>
        <div className="kpi"><b>{result.d_min.toFixed(2)}</b><span>Слабейший район (30%): {districtName(meta, result.d_min_district)}</span></div>
        <div className="kpi"><b className={result.n_crit ? 'neg' : 'pos'}>{result.n_crit}</b><span>Критических показателей (&lt;{meta.rules.critical_threshold}) · было {result.base_n_crit}</span></div>
        <div className="kpi">
          {oracle ? <><b>{oracle.percentile}%</b><span>Перцентиль среди {oracle.n_valid_sets.toLocaleString('ru')} допустимых · до максимума {oracle.best_score} не хватает {oracle.gap_to_best}</span></> : <><b>…</b><span>Оракул считает</span></>}
        </div>
      </div>

      <div className="grid three">
        <div className="panel">
          <h2>Районы: до и после</h2>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={districtData} barGap={2}>
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis dataKey="name" stroke={TXT} tickLine={false} />
              <YAxis domain={[40, 70]} stroke={TXT} tickLine={false} width={30} />
              <Tooltip cursor={{ fill: '#ffffff08' }} />
              <Legend />
              <Bar dataKey="До" fill="#4a5a7a" radius={[4, 4, 0, 0]} />
              <Bar dataKey="После" fill="#f5b041" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="panel">
          <h2>Вклад каждой меры в Score</h2>
          <div className="small muted mb">Маржинальный вклад: Score(все) − Score(без этой меры)</div>
          <ResponsiveContainer width="100%" height={210}>
            <BarChart data={measureData} layout="vertical" margin={{ left: 10, right: 20 }}>
              <CartesianGrid stroke={GRID} horizontal={false} />
              <XAxis type="number" stroke={TXT} tickLine={false} />
              <YAxis type="category" dataKey="name" width={120} stroke={TXT} tickLine={false} tick={{ fontSize: 11 }} />
              <Tooltip cursor={{ fill: '#ffffff08' }} formatter={(v: unknown, _n: unknown, p: { payload?: { cost?: number } }) => [`${signed(Number(v))} (стоимость ${p.payload?.cost})`, 'Вклад']} />
              <ReferenceLine x={0} stroke={TXT} />
              <Bar dataKey="Вклад" radius={[0, 4, 4, 0]}>
                {measureData.map((m, i) => <Cell key={i} fill={DIR_HEX[m.dir]} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="panel">
          <h2>Направления (средневзвеш. по городу)</h2>
          <ResponsiveContainer width="100%" height={240}>
            <RadarChart data={dirData} outerRadius={85}>
              <PolarGrid stroke={GRID} />
              <PolarAngleAxis dataKey="name" stroke={TXT} tick={{ fontSize: 11 }} />
              <PolarRadiusAxis domain={[45, 65]} stroke={TXT} tick={false} axisLine={false} />
              <Radar dataKey="До" stroke="#4a5a7a" fill="#4a5a7a" fillOpacity={0.35} />
              <Radar dataKey="После" stroke="#f5b041" fill="#f5b041" fillOpacity={0.35} />
              <Legend />
              <Tooltip />
            </RadarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="panel">
        <div className="row spread mb">
          <h2>Тепловая карта показателей после мер</h2>
          <span className="small muted">В скобках — изменение. Красная рамка — критическое значение (&lt;{meta.rules.critical_threshold}), штраф −1.</span>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table className="heat">
            <thead><tr><th>Район</th>{meta.indicators.map((i) => <th key={i.code} className="num" title={i.name} style={{ textAlign: 'center' }}>{i.code}</th>)}<th className="num">Балл</th></tr></thead>
            <tbody>
              {result.districts.map((d) => (
                <tr key={d.district_id}>
                  <td>{d.name} <span className="muted small">{Math.round(d.population_share * 100)}%</span></td>
                  {d.indicators.map((i) => {
                    const v = i.final
                    const hue = v < 40 ? 0 : v < 60 ? 35 : 150
                    return (
                      <td key={i.code} className={`cell ${i.critical_after ? 'crit' : ''}`} style={{ background: `hsla(${hue}, 70%, 45%, ${0.15 + Math.min(1, v / 100) * 0.35})` }} title={`${i.code}: ${i.base} → ${i.final}`}>
                        {v.toFixed(0)}{Math.abs(i.delta) > 0.001 && <span className={`small ${i.delta > 0 ? 'pos' : 'neg'}`}> ({signed(i.delta, 1)})</span>}
                      </td>
                    )
                  })}
                  <td className="num"><b>{d.score_after.toFixed(1)}</b> <span className={`small ${d.score_after >= d.score_before ? 'pos' : 'neg'}`}>{signed(d.score_after - d.score_before, 1)}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {result.synergies.length > 0 && <div className="mt small"><b>Синергии:</b> {result.synergies.map((s) => s.note).join('; ')}</div>}
      </div>
    </div>
  )
}
