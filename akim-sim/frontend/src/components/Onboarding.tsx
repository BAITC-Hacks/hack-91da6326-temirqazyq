import type { Meta } from '../api'

/* Экран первого запуска. Показывается один раз (флаг в localStorage) и заново — по кнопке «?».
   Отвечает на три вопроса, на которые интерфейс раньше не отвечал нигде: что это, какая цель
   и по какому ориентиру понять, хорош ли результат. */
export default function Onboarding({
  meta,
  bestScore,
  onStart,
  onExample,
}: {
  meta: Meta
  bestScore: number | null
  onStart: () => void
  onExample: () => void
}) {
  const N = meta.rules.decisions_required
  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-label="Что это за симулятор">
      <div className="overlay-card">
        <p className="eyebrow">Симулятор управления городом</p>
        <h2>Вы — аким Астаны на пять часов</h2>
        <p className="muted">
          У вас {meta.rules.budget} условных единиц бюджета и пять районов с разными проблемами. Нужно выбрать
          ровно {N} мероприятий и посмотреть, что станет с городом через {meta.rules.horizon_quarters} кварталов.
        </p>

        <h3 className="mt">Цель</h3>
        <p>
          Поднять <b>оценку качества жизни</b> как можно выше. Вот ориентиры, между которыми идёт вся борьба:
        </p>
        <div className="scale-marks">
          <div>
            <b className="num">{meta.base_score}</b>
            <span>ничего не делать</span>
          </div>
          <div className="arrow">→</div>
          <div>
            <b className="num">{bestScore ?? '…'}</b>
            <span>лучший возможный план</span>
          </div>
        </div>
        <p className="small muted">
          Разрыв выглядит маленьким, но внутри него — все {meta.measures.length} мер и сотни тысяч комбинаций.
          Команды соревнуются за десятые доли балла.
        </p>

        <h3 className="mt">Как устроена оценка</h3>
        <ul className="small">
          <li>70% — средний балл районов, взвешенный по населению.</li>
          <li>30% — балл самого слабого района. Вылизать центр и забыть окраину не получится.</li>
          <li>Минус 1 балл за каждый показатель ниже 40: это провал, который нельзя игнорировать.</li>
        </ul>

        <div className="notice info mt">
          <span className="ic">i</span>
          <span>
            Все числа считает детерминированный движок, а не языковая модель. AI только объясняет результат,
            критикует план и предлагает замены — и каждая его рекомендация пересчитывается движком заново.
          </span>
        </div>

        <div className="row mt" style={{ marginTop: 20 }}>
          <button className="primary" onClick={onStart}>Собрать свой план</button>
          <button onClick={onExample}>Показать на готовом примере</button>
        </div>
      </div>
    </div>
  )
}
