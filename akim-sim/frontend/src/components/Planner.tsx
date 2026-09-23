import { useEffect, useState } from 'react';
import { Popover, Segmented } from 'antd';
import {
  api,
  type Decision,
  type Guide,
  type Meta,
  type ValidationResult,
  type World,
} from '../api';
import {
  DIR_COLORS,
  DIR_SHORT,
  EXAMPLE_DECISIONS,
  districtName,
  measureName,
  plural,
  signed,
} from '../lib';
import { CodesLegend, Hint } from './Viz';
import { Bundles, DirectionSteps, DistrictAdvice } from './Guide';

type Props = {
  meta: Meta;
  world: World | null;
  decisions: Decision[];
  validation: ValidationResult | null;
  busy: boolean;
  bestScore: number | null;
  onChange: (d: Decision[]) => void;
  onScore: () => void;
};

export default function Planner({
  meta,
  world,
  decisions,
  validation,
  busy,
  bestScore,
  onChange,
  onScore,
}: Props) {
  const [pick, setPick] = useState<Record<string, string>>({});
  const [activeDirection, setActiveDirection] = useState('all');
  const [mode, setMode] = useState<'all' | 'step'>('all');
  const [guide, setGuide] = useState<Guide | null>(null);

  /* Подсказчик движка: на сколько сдвинет оценку каждый возможный следующий ход.
     Пересчитывается при каждом изменении набора — на сервере это десятки миллисекунд. */
  useEffect(() => {
    let alive = true;
    const t = setTimeout(() => {
      api
        .guide(decisions, world?.event_id ?? null)
        .then((g) => {
          if (alive) setGuide(g);
        })
        .catch(() => {
          if (alive) setGuide(null);
        });
    }, 200);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [decisions, world?.event_id]);

  /* эффект конкретного варианта «мера + выбранный район» */
  const deltaOf = (mid: string, scope: string, district?: string) => {
    if (!guide) return null;
    const want = scope === 'city' ? null : (district ?? null);
    if (scope === 'district' && !want) return null;
    return (
      guide.options.find((o) => o.measure_id === mid && o.district_id === want) ?? null
    );
  };

  const budget = world?.budget ?? meta.rules.budget;
  const blocked = new Set(world?.blocked_measures ?? []);
  const chosen = new Map(decisions.map((d) => [d.measure_id, d]));
  const N = meta.rules.decisions_required;
  const full = decisions.length >= N;
  const perDir = (dir: string) =>
    validation?.per_direction[dir] ??
    decisions.filter(
      (d) =>
        meta.measures.find((m) => m.id === d.measure_id)?.direction === dir,
    ).length;

  const byCode = new Map(meta.indicators.map((i) => [i.code, i]));

  const add = (mid: string, district: string | null) => {
    if (full || chosen.has(mid)) return;
    onChange([...decisions, { measure_id: mid, district_id: district }]);
  };
  const remove = (i: number) => onChange(decisions.filter((_, j) => j !== i));

  const cost =
    validation?.total_cost ??
    decisions.reduce(
      (s, d) =>
        s + (meta.measures.find((m) => m.id === d.measure_id)?.cost ?? 0),
      0,
    );
  const over = cost > budget;
  const pct = Math.min(100, (cost / budget) * 100);
  const directionEntries = Object.entries(meta.directions);
  const visibleDirections = directionEntries.filter(
    ([dir]) => activeDirection === 'all' || dir === activeDirection,
  );

  /* Почему кнопка «Добавить» недоступна — молчащая кнопка хуже объяснённой.
     inline=true только для причин, специфичных для этой карточки: общее «слоты заняты»
     повторять под каждой из четырнадцати мер бессмысленно, оно видно по счётчику. */
  const blockReason = (
    mid: string,
    scope: string,
    dir: string,
  ): { text: string; inline: boolean } | null => {
    if (blocked.has(mid))
      return { text: 'Заблокировано событием', inline: true };
    if (perDir(dir) >= meta.rules.max_per_direction)
      return {
        text: `На это направление уже ${meta.rules.max_per_direction} меры`,
        inline: true,
      };
    if (full)
      return {
        text: `Уже выбрано ${N} из ${N} — сначала уберите что-нибудь`,
        inline: false,
      };
    if (scope === 'district' && !pick[mid])
      return { text: 'Сначала выберите район', inline: true };
    return null;
  };

  return (
    <div className="grid planner">
      <div>
        <section className="panel howto mb">
          <div>
            <p className="eyebrow">Ваш первый ход</p>
            <h2>Соберите план для города</h2>
            <p className="muted">
              Выберите {N}{' '}
              {plural(N, 'мероприятие', 'мероприятия', 'мероприятий')} в
              пределах бюджета {budget} единиц. Меры с пометкой «район» требуют
              выбора района, «город» действуют на все пять. Затем нажмите
              «Рассчитать результат».
            </p>
            <p className="goal" data-tour="goal">
              Цель — поднять <Hint term="score">оценку качества жизни</Hint> как
              можно выше. Ничего не делать —{' '}
              <b className="num">{meta.base_score}</b>
              {bestScore != null && (
                <>
                  , лучший возможный план — <b className="num">{bestScore}</b>
                </>
              )}
              .
            </p>
            <div className="row mt">
              <button
                className="small ghost"
                onClick={() => onChange(EXAMPLE_DECISIONS)}
              >
                Загрузить пример из датасета
              </button>
              <span className="tiny dim">
                набор за 95 единиц, который закрывает оба провала в Нуре
              </span>
            </div>
          </div>
          <div className="howto-steps" aria-label="Порядок действий">
            <span className={decisions.length < N ? 'current' : ''}>
              <b>1</b> Выбрать {N} мер
            </span>
            <span
              className={
                decisions.length === N && validation?.valid ? 'current' : ''
              }
            >
              <b>2</b> Рассчитать
            </span>
            <span>
              <b>3</b> Изучить разбор AI
            </span>
          </div>
        </section>

        {guide && <DistrictAdvice guide={guide} meta={meta} />}
        {guide && <Bundles bundles={guide.bundles} onTake={onChange} />}

        <div className="row spread mb">
          <div>
            <h2>Каталог мероприятий</h2>
            <p className="small muted" style={{ margin: '2px 0 0' }}>
              Всего {meta.measures.length} мер: стоимость, <Hint term="lag">лаг</Hint> и на
              какие показатели влияет.{' '}
              <Popover
                placement="bottomLeft"
                title="Показатели качества жизни"
                content={
                  <div style={{ maxWidth: 520 }}>
                    <CodesLegend meta={meta} />
                  </div>
                }
              >
                <button
                  className="qmark"
                  data-tour="codes"
                  aria-label="Что означают коды T1, E2, S1"
                >
                  ?
                </button>
              </Popover>
            </p>
          </div>
          <span className="small muted num">
            {decisions.length} из {N} выбрано
          </span>
        </div>


        <div className="row spread mb">
          <Segmented
            value={mode}
            onChange={(v) => {
              setMode(v as 'all' | 'step');
              setActiveDirection(v === 'step' ? directionEntries[0][0] : 'all');
            }}
            options={[
              { label: 'Все сразу', value: 'all' },
              { label: 'Пошагово', value: 'step' },
            ]}
          />
        </div>

        {mode === 'step' ? (
          <DirectionSteps
            meta={meta}
            active={activeDirection}
            counts={Object.fromEntries(directionEntries.map(([d]) => [d, perDir(d)]))}
            onPick={setActiveDirection}
          />
        ) : (
          <div className="filters mb" aria-label="Фильтр направлений">
            <button
              className={`small ${activeDirection === 'all' ? 'active' : ''}`}
              onClick={() => setActiveDirection('all')}
            >
              Все
            </button>
            {directionEntries.map(([dir, title]) => (
              <button
                key={dir}
                className={`small ${activeDirection === dir ? 'active' : ''}`}
                style={{ ['--dir' as string]: DIR_COLORS[dir] }}
                onClick={() => setActiveDirection(dir)}
              >
                <i className="swatch" />
                {title}
              </button>
            ))}
          </div>
        )}

        {visibleDirections.map(([dir, title]) => {
          const used = perDir(dir);
          return (
            <div
              className="dir-block"
              key={dir}
              style={{ ['--dir' as string]: DIR_COLORS[dir] }}
            >
              <h3>
                <i />
                {title}
                <span className="dir-note">
                  · выбрано {used} из максимум {meta.rules.max_per_direction}
                </span>
              </h3>
              <div className="measures">
                {meta.measures
                  .filter((m) => m.direction === dir)
                  .map((m, mi) => {
                    const sel = chosen.get(m.id);
                    const reason = sel ? null : blockReason(m.id, m.scope, dir);
                    const isBlocked = blocked.has(m.id);
                    return (
                      <div
                        key={m.id}
                        className={`measure ${sel ? 'selected' : ''} ${isBlocked ? 'blocked' : ''}`}
                        data-tour={
                          dir === 'transport' && mi === 0
                            ? 'measure'
                            : undefined
                        }
                        style={{ ['--dir' as string]: DIR_COLORS[dir] }}
                      >
                        <div className="m-head">
                          <span className="m-id">{m.id}</span>
                          <span className="m-name">{m.name}</span>
                        </div>

                        <div className="m-stats">
                          <div className="m-cost">
                            <b className="num">{m.cost}</b>
                            <span>единиц</span>
                          </div>
                          <div>
                            <b className="num">{m.lag} кв.</b>
                            <span><Hint term="lag">лаг</Hint></span>
                          </div>
                          <div>
                            <b className="num">
                              {Math.round(((meta.rules.horizon_quarters - m.lag) / meta.rules.horizon_quarters) * 100)}%
                            </b>
                            <span>успеет</span>
                          </div>
                          <span className="m-scope">{m.scope === 'city' ? 'весь город' : 'один район'}</span>
                        </div>

                        {(() => {
                          const o = sel ? null : deltaOf(m.id, m.scope, pick[m.id])
                          if (sel) return null
                          if (!o) {
                            return m.scope === 'district' ? (
                              <div className="m-delta empty">Выберите район — покажу, что изменится</div>
                            ) : null
                          }
                          return (
                            <div className={`m-delta ${o.delta > 0 ? 'up' : o.delta < 0 ? 'down' : 'flat'}`}>
                              <b className="num">{signed(o.delta)}</b>
                              <span>к оценке города, если добавить сейчас</span>
                            </div>
                          )
                        })()}

                        <ul className="m-fx">
                          {Object.entries(m.effects).map(([k, v]) => (
                            <li key={k}>
                              <b>{k}</b>
                              <span className="n">{byCode.get(k)?.name ?? k}</span>
                              <span className={`v ${v >= 0 ? 'pos' : 'neg'}`}>{v > 0 ? '+' : ''}{v}</span>
                            </li>
                          ))}
                        </ul>

                        <div className="actions">
                          {sel ? (
                            <>
                              <span className="small muted" style={{ flex: 1 }}>
                                В плане: {districtName(meta, sel.district_id)}
                              </span>
                              <button className="small ghost" onClick={() => remove(decisions.indexOf(sel))}>
                                Убрать
                              </button>
                            </>
                          ) : (
                            <>
                              {m.scope === 'district' && !isBlocked && (
                                <select
                                  value={pick[m.id] ?? ''}
                                  onChange={(e) => setPick({ ...pick, [m.id]: e.target.value })}
                                  aria-label={`Район для ${m.id}`}
                                >
                                  <option value="">Район…</option>
                                  {meta.districts.map((d) => (
                                    <option key={d.id} value={d.id}>{d.name}</option>
                                  ))}
                                </select>
                              )}
                              <button
                                className="small primary"
                                disabled={!!reason}
                                title={reason?.text}
                                onClick={() => add(m.id, m.scope === 'district' ? pick[m.id] : null)}
                              >
                                Добавить
                              </button>
                            </>
                          )}
                        </div>
                        {reason?.inline && (
                          <div className="tiny dim">{reason.text}</div>
                        )}
                      </div>
                    );
                  })}
              </div>
            </div>
          );
        })}
      </div>

      <div className="panel sticky">
        <div className="row spread mb">
          <h2>Пять решений</h2>
          <span className="muted small num">
            {decisions.length}/{N}
          </span>
        </div>

        <div className="slots" data-tour="slots">
          {Array.from({ length: N }).map((_, i) => {
            const d = decisions[i];
            const m = d && meta.measures.find((x) => x.id === d.measure_id);
            return (
              <div
                key={i}
                className={`slot ${d ? 'filled' : ''}`}
                style={{
                  ['--dir' as string]: m ? DIR_COLORS[m.direction] : undefined,
                }}
              >
                <span className="n">{i + 1}</span>
                {d && m ? (
                  <>
                    <div className="body">
                      <div className="t">
                        {d.measure_id} · {measureName(meta, d.measure_id)}
                      </div>
                      <div className="tiny muted">
                        {districtName(meta, d.district_id)} · {m.cost} ед. · лаг{' '}
                        {m.lag} кв.
                      </div>
                    </div>
                    <button
                      className="small ghost"
                      onClick={() => remove(i)}
                      aria-label="Убрать решение"
                    >
                      ✕
                    </button>
                  </>
                ) : (
                  <span className="tiny dim">
                    Пусто — добавьте меру из каталога
                  </span>
                )}
              </div>
            );
          })}
        </div>

        <div className="mt row spread">
          <span className="small muted">
            <Hint term="budget">Бюджет</Hint>
          </span>
          <b className="num">
            {cost} / {budget}
          </b>
        </div>
        <div className="meter" data-tour="budget">
          <i className={over ? 'over' : ''} style={{ width: `${pct}%` }} />
        </div>
        <div className="tiny dim" style={{ marginTop: 4 }}>
          {over
            ? `Перебор на ${cost - budget} — уберите или замените меру`
            : `Остаток ${budget - cost}: не переносится и бонуса не даёт`}
        </div>

        <h3 className="mt">Мер по направлениям</h3>
        <div className="dircount">
          {directionEntries.map(([dir, title]) => {
            const n = perDir(dir);
            return (
              <div
                key={dir}
                className={n > meta.rules.max_per_direction ? 'over' : ''}
                style={{ ['--dir' as string]: DIR_COLORS[dir] }}
                title={`${title}: ${n} из максимум ${meta.rules.max_per_direction}`}
              >
                <b>{n}</b>
                {DIR_SHORT[dir] ?? title}
              </div>
            );
          })}
        </div>

        <div className="mt issues">
          {validation?.valid && (
            <div className="notice good">
              <span className="ic">✓</span>
              <span>Все правила соблюдены — можно считать Score</span>
            </div>
          )}
          {validation?.issues.map((issue, k) => (
            <div key={k} className="notice bad">
              <span className="ic">!</span>
              <span>{issue.message}</span>
            </div>
          ))}
        </div>

        <div className="mt row" data-tour="calc">
          <button
            className="primary"
            disabled={!validation?.valid || busy}
            onClick={onScore}
            style={{ flex: 1 }}
          >
            {busy ? <><span className="spinner" /> Считаем…</> : 'Рассчитать результат'}
          </button>
          <button
            className="ghost"
            onClick={() => onChange([])}
            disabled={!decisions.length}
          >
            Сброс
          </button>
        </div>

        <h3 className="mt" data-tour="rules">
          Правила, которые проверяет сервер
        </h3>
        <ul
          className="tiny muted"
          style={{ margin: '4px 0 0', paddingLeft: 18 }}
        >
          <li>Ровно {N} решений, каждая мера не более одного раза</li>
          <li>Сумма стоимости ≤ {budget}</li>
          <li>
            Не более {meta.rules.max_per_direction} мер на одно направление
          </li>
          {meta.incompatibilities.map((inc) => (
            <li key={`${inc.a}-${inc.b}`}>
              {inc.a} и {inc.b} несовместимы
              {inc.scope === 'same_district' ? ' в одном районе' : ''} —{' '}
              {inc.reason.toLowerCase()}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
