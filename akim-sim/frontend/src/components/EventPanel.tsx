import { useState } from 'react'
import type { CustomEvent, EventOut, Meta } from '../api'
import { districtName, signed } from '../lib'
import { Hint } from './Viz'

type Props = {
  meta: Meta
  event: EventOut | null
  activeEventId: string | null
  loading: boolean
  hasPlan: boolean
  onTrigger: (id: string | null) => void
  onEnterWorld: () => void
  onReset: () => void
  custom: CustomEvent | null
  customBusy: boolean
  customError: string
  onCustom: (text: string) => void
}
/* Шаблон вместо трёх кнопок-примеров: он показывает, какие сведения нужны,
   и при этом не подсовывает готовый ответ. */
const TEMPLATE =
  'Что случилось: \n' +
  'Где (район или весь город): \n' +
  'Что из-за этого стало хуже: \n' +
  'Повлияло ли на бюджет: ';

export default function EventPanel({
  meta, event, activeEventId, loading, hasPlan, onTrigger, onEnterWorld, onReset,
  custom, customBusy, customError, onCustom,
}: Props) {
  const [choice, setChoice] = useState<string>('')
  const [text, setText] = useState('')

  return (
    <div className="grid">
      <div className="panel">
        <div className="row spread">
          <div style={{ maxWidth: 680 }}>
            <h2>«Чёрный лебедь»</h2>
            <div className="small muted">
              Неожиданное городское событие меняет исходные показатели, блокирует меру или режет бюджет. Ваш план
              пересчитывается в новом мире — и может перестать быть валидным. Это стресс-тест: хороший план не должен
              рассыпаться от одной новости.
            </div>
          </div>
          <div className="row">
            <select value={choice} onChange={(e) => setChoice(e.target.value)} aria-label="Выбор события">
              <option value="">Случайное событие</option>
              {meta.events.map((e) => (
                <option key={e.id} value={e.id}>{e.title}</option>
              ))}
            </select>
            <button className="primary" disabled={!hasPlan || loading} onClick={() => onTrigger(choice || null)}>
              {loading ? <><span className="spinner" /> Запускаем…</> : 'Запустить событие'}
            </button>
            {activeEventId && <button className="ghost" onClick={onReset}>Вернуться в базовый мир</button>}
          </div>
        </div>

        {!hasPlan && (
          <div className="notice info mt">
            <span className="ic">→</span>
            <span>Сначала соберите валидный набор из {meta.rules.decisions_required} решений — событие покажет, как он просядет.</span>
          </div>
        )}
        {activeEventId && (
          <div className="notice bad mt">
            <span className="ic">⚡</span>
            <span>
              Активный мир: <b>{meta.events.find((e) => e.id === activeEventId)?.title}</b> — все расчёты, оракул,
              лидерборд и AI-анализ идут в нём, а не в базовом.
            </span>
          </div>
        )}
      </div>

      {event && (
        <div className="grid two">
          <div className="panel event-card">
            <h2>{event.event.title}</h2>
            <p>{event.narration.briefing}</p>
            <p className="muted">{event.narration.impact_summary}</p>
            <h3>Что советует AI</h3>
            <ul>{event.narration.advice.map((a, i) => <li key={i}>{a}</li>)}</ul>
            <div className="tiny dim">
              {event.narration._mode === 'llm' ? 'Нарратив: LLM' : 'Нарратив: шаблонный режим'}
            </div>
          </div>

          <div className="panel">
            <h2>Что именно изменилось</h2>
            <table className="mt">
              <tbody>
                {event.event.shocks.map((s, i) => (
                  <tr key={i}>
                    <td>Шок по показателю</td>
                    <td>{districtName(meta, s.district)} · {s.indicator}</td>
                    <td className={`num ${s.delta < 0 ? 'neg' : 'pos'}`}>{signed(s.delta, 0)}</td>
                  </tr>
                ))}
                {event.event.blocked_measures.length > 0 && (
                  <tr>
                    <td>Больше недоступно</td>
                    <td colSpan={2}>{event.event.blocked_measures.join(', ')}</td>
                  </tr>
                )}
                {event.event.budget_delta !== 0 && (
                  <tr>
                    <td>Бюджет урезан</td>
                    <td colSpan={2} className="neg num">{signed(event.event.budget_delta, 0)} → {event.world.budget}</td>
                  </tr>
                )}
                <tr>
                  <td>Score плана до события</td>
                  <td colSpan={2} className="num">{event.score_before ?? '—'}</td>
                </tr>
                <tr>
                  <td>Score, если ничего не менять</td>
                  <td colSpan={2} className={`num ${event.score_before != null && event.score_after_if_unchanged < event.score_before ? 'neg' : ''}`}>
                    {event.score_after_if_unchanged}
                  </td>
                </tr>
                <tr>
                  <td>Новая <Hint term="score">база мира</Hint></td>
                  <td colSpan={2} className="num">{event.base_score_after}</td>
                </tr>
                <tr>
                  <td>План всё ещё валиден?</td>
                  <td colSpan={2}>
                    {event.plan_still_valid ? (
                      <span className="pos">да</span>
                    ) : (
                      <span className="neg">нет — {event.validation.issues.map((i) => i.message).join('; ')}</span>
                    )}
                  </td>
                </tr>
              </tbody>
            </table>
            <button className="primary mt" onClick={onEnterWorld} disabled={activeEventId === event.event.id}>
              Перепланировать в этом мире →
            </button>
          </div>
        </div>
      )}

      {/* Своя проблема: модель переводит текст в параметры, последствия считает движок. */}
      <div className="panel">
        <h2>Своя проблема — своими словами</h2>
        <p className="small muted">
          Шесть готовых сценариев выше — не весь список бед. Опишите, что случилось в городе, и AI переведёт
          описание в конкретные показатели: какие районы просядут, на сколько, нужно ли резать бюджет. Дальше
          последствия посчитает тот же детерминированный движок, что и всегда.
        </p>

        <textarea
          className="mt"
          rows={4}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={"Опишите, что случилось в городе. Например:\n«Зимой в Сарыарке прорвало теплотрассу, без отопления остались десятки домов, а на аварийный ремонт ушли деньги из бюджета»"}
          maxLength={1200}
          disabled={!hasPlan}
        />
        <div className="row spread mt">
          <button
            className="small with-icon"
            disabled={!hasPlan}
            onClick={() => setText(TEMPLATE)}
          >
            <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <rect x="3" y="2" width="10" height="12" rx="1.5" />
              <path d="M5.75 5.5h4.5M5.75 8h4.5M5.75 10.5h2.5" />
            </svg>
            Подставить шаблон
          </button>
          <div className="row">
            <span className="tiny dim">{text.length}/1200</span>
            <button
              className="primary"
              disabled={!hasPlan || customBusy || text.trim().length < 10}
              onClick={() => onCustom(text)}
            >
              {customBusy ? <><span className="spinner" /> Разбираем описание…</> : 'Разобрать и посчитать'}
            </button>
          </div>
        </div>
        {!hasPlan && <div className="notice info mt"><span className="ic">→</span><span>Сначала соберите валидный план — иначе не с чем сравнивать последствия.</span></div>}
        {customError && <div className="notice bad mt"><span className="ic">!</span><span>{customError}</span></div>}
      </div>

      {custom && (
        <div className="grid two">
          <div className="panel event-card">
            <div className="row spread mb">
              <h2>{custom.event.title}</h2>
              {custom._mode === 'llm'
                ? <span className="badge on">разобрано моделью</span>
                : <span className="badge warn"><Hint term="fallback">по ключевым словам</Hint></span>}
            </div>
            <p className="small muted">{custom.interpretation}</p>
            <p>{custom.narration.briefing}</p>
            <h3>Что делать</h3>
            <ul>{custom.narration.advice.map((a, i) => <li key={i}>{a}</li>)}</ul>
          </div>

          <div className="panel">
            <h2>Во что это превратилось в модели</h2>
            <table className="mt">
              <tbody>
                {custom.event.shocks.map((s, i) => (
                  <tr key={i}>
                    <td>{districtName(meta, s.district)}</td>
                    <td className="dim">{meta.indicators.find((x) => x.code === s.indicator)?.name ?? s.indicator}</td>
                    <td className={`num ${s.delta < 0 ? 'neg' : 'pos'}`}>{signed(s.delta, 0)}</td>
                  </tr>
                ))}
                {custom.event.blocked_measures.length > 0 && (
                  <tr><td>Стало недоступно</td><td colSpan={2}>{custom.event.blocked_measures.join(', ')}</td></tr>
                )}
                {custom.event.budget_delta !== 0 && (
                  <tr><td>Бюджет</td><td colSpan={2} className="neg num">{signed(custom.event.budget_delta, 0)} → {custom.world.budget}</td></tr>
                )}
                <tr>
                  <td>Ваш Score</td>
                  <td colSpan={2} className="num">
                    {custom.score_before ?? '—'} → <b className={custom.score_before != null && custom.score_after_if_unchanged < custom.score_before ? 'neg' : ''}>{custom.score_after_if_unchanged}</b>
                  </td>
                </tr>
                <tr>
                  <td>План уцелел?</td>
                  <td colSpan={2}>
                    {custom.plan_still_valid
                      ? <span className="pos">да</span>
                      : <span className="neg">нет — {custom.validation.issues.map((i) => i.message).join('; ')}</span>}
                  </td>
                </tr>
              </tbody>
            </table>

            <h3 className="mt">Лучшее, что возможно в этом мире</h3>
            <p className="small muted">
              Движок перебрал все {custom.rescue.n_valid.toLocaleString('ru')} допустимых наборов уже после
              катастрофы. Максимум — <b>{custom.rescue.best_score}</b>:
            </p>
            <ul className="small">{custom.rescue.best_set_human.map((x, i) => <li key={i}>{x}</li>)}</ul>
          </div>
        </div>
      )}
    </div>
  )
}
