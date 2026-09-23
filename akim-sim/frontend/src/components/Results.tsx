import { useState } from 'react'
import { Tooltip } from 'antd'
import type { Analysis, Meta, ScoreResult } from '../api'
import { DIR_TITLE, districtName, heatFill, signed } from '../lib'
import { CodesLegend, DivergingBars, Dumbbell, Fold, HeatLegend, Hint } from './Viz'

export default function Results({ meta, result, analysis }: { meta: Meta; result: ScoreResult; analysis: Analysis | null }) {
  const oracle = analysis?.oracle
  const thr = meta.rules.critical_threshold
  /* Детали развёрнуты на широком экране (жюри видит глубину сразу) и свёрнуты на узком,
     где иначе пришлось бы пролистывать таблицу 5×10, чтобы добраться до разбора AI. */
  const [cell, setCell] = useState<{ d: string; code: string } | null>(null)
  const [details, setDetails] = useState(() => typeof window === 'undefined' || window.innerWidth > 1100)

  const districtRows = result.districts.map((d) => ({ label: d.name, before: d.score_before, after: d.score_after }))
  const directionRows = result.directions.map((d) => ({ label: DIR_TITLE[d.direction] ?? d.name, before: d.before, after: d.after }))
  const measureRows = result.measures.map((m) => ({
    label: `${m.measure_id} · ${m.name} — ${districtName(meta, m.district_id)}`,
    value: m.shapley_score,
    hint:
      `стоимость ${m.cost}, лаг ${m.lag} кв. (успевает ${Math.round(m.realized_share * 100)}%). ` +
      `Если просто убрать эту меру из набора, Score изменится на ${signed(m.marginal_score)} — ` +
      `разница со вкладом по Шепли и есть эффект пересечения с другими мерами`,
  }))
  // Складываем ИМЕННО то, что показано на экране, и тем же способом округления:
  // toFixed и Math.round расходятся на половинках (0.475 → «0.47» против 0.48),
  // поэтому сумма считается через Number(toFixed(2)), как и каждое слагаемое.
  const shapleySum = result.measures.reduce((a, m) => a + Number(m.shapley_score.toFixed(2)), 0)

  return (
    <div className="grid">
      <div className="grid kpis">
        <div className="kpi hero" data-tone="total">
          <b>{result.score}</b>
          <span className="lbl">
            <Hint term="score">Оценка города</Hint>
          </span>
          <span className="sub">
            было {result.base_score} ·{' '}
            <span className={result.delta >= 0 ? 'pos' : 'neg'}>{signed(result.delta)}</span>
          </span>
          {oracle && (
            <div className="progress">
              <div className="meter">
                <i
                  style={{
                    width: `${Math.max(0, Math.min(100, ((result.score - result.base_score) / (oracle.best_score - result.base_score)) * 100))}%`,
                  }}
                />
              </div>
              <span className="tiny muted">
                <Hint term="progress">
                  {Math.round(((result.score - result.base_score) / (oracle.best_score - result.base_score)) * 100)}
                  % пути
                </Hint>{' '}
                до максимума {oracle.best_score}
              </span>
            </div>
          )}
        </div>

        <div className="kpi" data-tone="money">
          <b>
            {result.total_cost}
            <span className="unit">/ {result.budget}</span>
          </b>
          <span className="lbl">
            <Hint term="budget">Потрачено</Hint>
          </span>
          <span className="sub">осталось {result.remaining}</span>
        </div>

        {/* Две плитки одного тона: это ровно те слагаемые, из которых состоит оценка. */}
        <div className="kpi" data-tone="part">
          <b>{result.d_avg.toFixed(2)}</b>
          <span className="lbl">
            <Hint term="davg">Средний балл районов</Hint>
          </span>
          <span className="sub">70% оценки · было {result.base_d_avg.toFixed(2)}</span>
        </div>

        <div className="kpi" data-tone="part">
          <b>{result.d_min.toFixed(2)}</b>
          <span className="lbl">
            <Hint term="dmin">Слабейший район</Hint>
          </span>
          <span className="sub">
            30% оценки · {districtName(meta, result.d_min_district)}
          </span>
        </div>

        <div className="kpi" data-tone={result.n_crit ? 'bad' : 'good'}>
          <b className={result.n_crit ? 'neg' : 'pos'}>{result.n_crit}</b>
          <span className="lbl">
            <Hint term="critical">Провальных показателей</Hint>
          </span>
          <span className="sub">
            ниже {thr} · было {result.base_n_crit}
          </span>
        </div>

        <div
          className="kpi"
          data-tone={!oracle ? 'part' : oracle.percentile >= 50 ? 'good' : 'warn'}
        >
          <b className={oracle && oracle.percentile >= 50 ? 'pos' : undefined}>
            {oracle ? `${oracle.percentile}%` : '…'}
          </b>
          <span className="lbl">
            <Hint term="percentile" side="right">
              Лучше других планов
            </Hint>
          </span>
          <span className="sub">
            {oracle
              ? `из ${oracle.n_valid_sets.toLocaleString('ru')} возможных`
              : 'оракул перебирает наборы'}
          </span>
        </div>
      </div>

      {/* Одна фраза вместо шести чисел: без неё непонятно, 56.54 — это успех или провал. */}
      <div className={`notice ${result.delta >= 0 ? 'good' : 'bad'}`}>
        <span className="ic">{result.delta >= 0 ? '✓' : '!'}</span>
        <span>
          {result.delta >= 0
            ? `План поднял оценку города на ${signed(result.delta)} — с ${result.base_score} до ${result.score}.`
            : `План опустил оценку города на ${signed(result.delta)} — с ${result.base_score} до ${result.score}.`}
          {oracle && (
            <>
              {' '}Это лучше, чем <b>{oracle.percentile}%</b> всех {oracle.n_valid_sets.toLocaleString('ru')}{' '}
              возможных планов; до лучшего из них не хватает {oracle.gap_to_best}.
            </>
          )}
          {result.n_crit > 0
            ? ` Осталось ${result.n_crit} показателей ниже ${thr} — каждый отнимает по баллу.`
            : result.base_n_crit > 0
              ? ' Все провальные показатели закрыты — штрафа больше нет.'
              : ''}
        </span>
      </div>

      <div className="grid two">
        <div className="panel">
          <h2>Районы: до и после</h2>
          <p className="small muted mb">
            Каждая строка — район. Левая точка была до решений, правая стала после. Оценка города на 30% состоит
            из <Hint term="dmin">самого слабого</Hint> из них.
          </p>
          <Dumbbell rows={districtRows} />
        </div>
        <div className="panel">
          <h2>Направления по городу</h2>
          <p className="small muted mb">
            Средневзвешенное по населению значение показателей каждого направления — куда именно ушёл эффект мер.
          </p>
          <Dumbbell rows={directionRows} />
        </div>
      </div>

      <Fold
        title="Подробности расчёта"
        note="вклад каждой меры и показатели по районам"
        open={details}
        onToggle={() => setDetails((v) => !v)}
      >

      <div className="panel">
        <h2>Вклад каждой меры в Score</h2>
        <p className="small muted mb">
          Прирост разложен по мерам <Hint term="shapley">вектором Шепли</Hint>, поэтому вклады складываются в общий
          прирост точно: {result.measures.map((m) => signed(m.shapley_score)).join(' ')} ={' '}
          <b>{signed(shapleySum)}</b>. Зелёное вправо — мера добавила баллов, красное влево — забрала.
        </p>
        <DivergingBars rows={measureRows} />
        {result.synergies.length > 0 && (
          <div className="notice info mt">
            <span className="ic">＋</span>
            <span><b><Hint term="synergy">Синергия</Hint>:</b> {result.synergies.map((s) => s.note).join('; ')}</span>
          </div>
        )}
      </div>

      <div className="panel">
        <div className="row spread mb">
          <h2>Показатели по районам после мер</h2>
          <HeatLegend threshold={thr} />
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table className="heat">
            <thead>
              <tr>
                <th>Район · доля населения</th>
                {meta.indicators.map((i) => (
                  <th key={i.code} className="code" title={`${i.name}. ${i.meaning}`}>{i.code}</th>
                ))}
                <th className="num">Балл</th>
              </tr>
            </thead>
            <tbody>
              {result.districts.map((d) => (
                <tr key={d.district_id}>
                  <td>
                    {d.name}{' '}
                    <Tooltip
                      title={`В районе живёт ${Math.round(d.population_share * 100)}% горожан. С этим весом его балл входит в средний по городу, а средний — это 70% оценки. Провал в большом районе стоит дороже, чем в маленьком.`}
                    >
                      <span className="share">{Math.round(d.population_share * 100)}%</span>
                    </Tooltip>
                  </td>
                  {d.indicators.map((i) => {
                    const open = cell?.d === d.district_id && cell?.code === i.code
                    return (
                      <td
                        key={i.code}
                        className={`cell ${i.critical_after ? 'crit' : ''}${open ? ' picked' : ''}`}
                        style={{ background: heatFill(i.final) }}
                        title="Нажмите, чтобы увидеть, из чего сложилось число"
                        onClick={() => setCell(open ? null : { d: d.district_id, code: i.code })}
                      >
                        {i.final.toFixed(0)}
                        {Math.abs(i.delta) > 0.001 && (
                          <span className={`tiny ${i.delta > 0 ? 'pos' : 'neg'}`}> {signed(i.delta, 1)}</span>
                        )}
                      </td>
                    )
                  })}
                  <td className="num">
                    <b>{d.score_after.toFixed(1)}</b>{' '}
                    <span className={`tiny ${d.score_after >= d.score_before ? 'pos' : 'neg'}`}>
                      {signed(d.score_after - d.score_before, 1)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {cell && (() => {
          const dist = result.districts.find((x) => x.district_id === cell.d)!
          const ind = dist.indicators.find((x) => x.code === cell.code)!
          const info = meta.indicators.find((x) => x.code === cell.code)
          const sum = ind.contributions.reduce((a, c) => a + c.realized, 0)
          const clipped = Math.abs(ind.base + sum - ind.final) > 0.005
          return (
            <div className="derivation mt">
              <div className="row spread">
                <h3>
                  {dist.name} · {cell.code} {info ? `— ${info.name}` : ''}
                </h3>
                <button className="small ghost" onClick={() => setCell(null)}>Закрыть</button>
              </div>
              <table className="mt">
                <tbody>
                  <tr><td>Было до решений</td><td className="num">{ind.base.toFixed(2)}</td></tr>
                  {ind.contributions.map((c, k) => {
                    const m = meta.measures.find((x) => x.id === c.measure_id)
                    const share = m ? (meta.rules.horizon_quarters - m.lag) / meta.rules.horizon_quarters : 1
                    return (
                      <tr key={k}>
                        <td>
                          {c.kind === 'synergy' ? 'Синергия ' : ''}{c.measure_id}
                          {m && (
                            <span className="dim">
                              {' '}· эффект {signed(c.raw, 0)} × {share.toFixed(3)} (лаг {m.lag} кв.)
                            </span>
                          )}
                          {c.kind === 'synergy' && <span className="dim"> · бонус лагом не масштабируется</span>}
                        </td>
                        <td className={`num ${c.realized >= 0 ? 'pos' : 'neg'}`}>{signed(c.realized)}</td>
                      </tr>
                    )
                  })}
                  {!ind.contributions.length && <tr><td className="muted" colSpan={2}>Ни одна мера сюда не попала</td></tr>}
                  {clipped && (
                    <tr><td className="dim">Обрезано границей шкалы [0, 100]</td><td className="num dim">{signed(ind.final - ind.base - sum)}</td></tr>
                  )}
                  <tr>
                    <td><b>Стало</b>{ind.critical_after && <span className="neg"> · ниже {thr}, штраф −1 к Score</span>}</td>
                    <td className="num"><b>{ind.final.toFixed(2)}</b></td>
                  </tr>
                </tbody>
              </table>
            </div>
          )
        })()}

        <h3 className="mt">Что означают коды</h3>
        <CodesLegend meta={meta} />
      </div>
      </Fold>
    </div>
  )
}
