import type { Decision, Meta } from './api'

/* Палитра направлений под СВЕТЛУЮ поверхность stripe (панели белые).
   Порядок слотов — механизм CVD-безопасности, см. «Приложение» в DESIGN.md:
   смежная разделимость ΔE 16.3 (цель ≥8), порог нормального зрения ΔE 19.6 (жёсткий порог ≥15).
   Три оттенка из пяти дают на белом меньше 3:1 — это разрешённое послабление, но только
   вместе с подписью: свотч без текста рядом использовать нельзя. */
export const DIR_HEX: Record<string, string> = {
  transport: '#2a78d6',
  ecology: '#1baf7a',
  social: '#4a3aa7',
  safety: '#e87ba4',
  services: '#eda100',
}
export const DIR_COLORS: Record<string, string> = {
  transport: 'var(--dir-transport)',
  ecology: 'var(--dir-ecology)',
  social: 'var(--dir-social)',
  safety: 'var(--dir-safety)',
  services: 'var(--dir-services)',
}
/* Короткие названия направлений для графиков: полные из датасета («Социальная
   инфраструктура») не влезают в колонку подписи и обрезаются многоточием. */
export const DIR_TITLE: Record<string, string> = {
  transport: 'Транспорт', ecology: 'Экология', social: 'Соцсфера', safety: 'Безопасность', services: 'Сервисы',
}
export const DIR_SHORT: Record<string, string> = {
  transport: 'Трансп.', ecology: 'Эколог.', social: 'Соц.', safety: 'Безоп.', services: 'Сервис',
}

/* Слой данных: «до → после» — один тон двумя ступенями; полярность — статусные цвета. */
export const VIZ = {
  before: '#9ec5f4',   // одна шкала, две ступени: «до» отступает
  after: '#2a78d6',    // «после» — насыщенная
  good: '#0ca30c',
  critical: '#d03b3b',
  grid: '#e3e8ee',
  axis: '#64748d',
} as const

/* Тепловая карта: семантический heat critical → warning → good — разрешённое исключение
   из правила «один тон на магнитуду», но только вместе со шкалой-легендой (см. HeatLegend).
   Число в ячейке печатается всегда, поэтому цвет никогда не единственный канал. */
const HEAT_STOPS: [number, [number, number, number]][] = [
  [30, [208, 59, 59]],   // critical
  [55, [250, 178, 25]],  // warning
  [80, [12, 163, 12]],   // good
]
const HEAT_ALPHA = 0.2   // на белом фоне тонировка должна быть легче, иначе тушь перестаёт читаться

export function heatFill(v: number): string {
  const lastIndex = HEAT_STOPS.length - 1
  const x = Math.max(HEAT_STOPS[0][0], Math.min(HEAT_STOPS[lastIndex][0], v))
  for (let i = 0; i < lastIndex; i++) {
    const [x0, c0] = HEAT_STOPS[i]
    const [x1, c1] = HEAT_STOPS[i + 1]
    if (x <= x1) {
      const t = (x - x0) / (x1 - x0)
      const [r, g, b] = c0.map((c, k) => Math.round(c + (c1[k] - c) * t))
      return `rgba(${r}, ${g}, ${b}, ${HEAT_ALPHA})`
    }
  }
  const [r, g, b] = HEAT_STOPS[lastIndex][1]
  return `rgba(${r}, ${g}, ${b}, ${HEAT_ALPHA})`
}

/* Расшифровки терминов движка. Показываются компонентом <Hint>. */
export const TERMS: Record<string, string> = {
  score:
    'Astana Quality of Life Score — итоговая оценка города. 0.7 × средний балл районов + 0.3 × балл самого слабого района − 1 за каждую критическую ячейку. Без решений база равна 52.56.',
  davg:
    '70% оценки — средний балл районов, взвешенный по доле населения. Есиль весит 27%, Нура — 16%.',
  dmin:
    '30% оценки — балл самого слабого района. Из-за этой доли нельзя вылизать Есиль и забыть Нуру: подтянуть отстающего почти всегда выгоднее.',
  critical:
    'Критическая ячейка — пара «район × показатель» со значением ниже 40. Каждая отнимает от оценки ровно 1 балл. В базе их две: школы и поликлиники в Нуре.',
  lag:
    'Лаг — за сколько кварталов мера разворачивается. Горизонт всего 8 кварталов, поэтому мера успевает дать лишь долю (8 − лаг) / 8 своего эффекта: лаг 1 → 88%, лаг 4 → 50%.',
  marginal:
    'Маржинальный вклад = Score(все пять мер) − Score(без этой меры). Показывает, сколько мера даёт именно в этом наборе: с учётом синергий и того, что эффект мог упереться в потолок 100.',
  synergy:
    'Синергия — бонус, который начисляется, только если выбраны обе меры пары. Лагом он не масштабируется и попадает в район первой меры пары.',
  percentile:
    'Доля допустимых наборов, которые ваш план обошёл. Оракул перебирает их все, поэтому это точное число, а не оценка.',
  oracle:
    'Оракул — полный перебор всех допустимых наборов решений на numpy (около секунды). Это не эвристика: глобальный максимум найден точно, поэтому «до максимума не хватает X» — честный разрыв.',
  pareto:
    'Парето — для каждой суммы затрат лучший достижимый Score. Видно, что неизрасходованный остаток бюджета не всегда потеря: самый дешёвый валидный набор стоит 61 и даёт немало.',
  shapley:
    'Вектор Шепли — способ честно разделить общий прирост между мерами. Вклад каждой усредняется по всем порядкам, в которых меры можно было добавлять, поэтому сумма вкладов в точности равна общему приросту. Простая разность «со мерой минус без меры» так не умеет: бонус синергии засчитался бы дважды.',
  progress:
    'Куда полезнее сырого Score. Весь достижимый диапазон — всего около пяти баллов: от 52.04 у худшего допустимого плана до 57.24 у лучшего. Проценты показывают, какую часть этого пути вы прошли.',
  verified:
    'Рекомендация пересчитана движком на сервере, а не взята из ответа модели. Если бы модель выдумала число, здесь стояло бы «не прошло валидацию».',
  budget:
    'Бюджет одинаков у всех команд. Остаток не переносится и бонуса не даёт, но тратить всё до копейки не обязательно — иногда дешёвый набор выигрывает у дорогого.',
  fallback:
    'Шаблонный режим — объяснения собраны шаблонами, а не моделью. Числа при этом верные: они из той же трассы расчёта. Чтобы включить живой язык, задайте в файле .env две строки — LLM_PROVIDER (openai, nvidia или custom) и LLM_API_KEY — и перезапустите сервер. Всё остальное работает без ключа.',
}

export function measureName(meta: Meta, id: string) {
  return meta.measures.find((m) => m.id === id)?.name ?? id
}
export function districtName(meta: Meta, id: string | null) {
  if (!id) return 'весь город'
  return meta.districts.find((d) => d.id === id)?.name ?? id
}
export function decisionLabel(meta: Meta, d: Decision) {
  return `${d.measure_id} · ${measureName(meta, d.measure_id)} — ${districtName(meta, d.district_id)}`
}
/** Русское склонение после числа: plural(5, 'мероприятие','мероприятия','мероприятий'). */
export function plural(n: number, one: string, few: string, many: string) {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return one
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few
  return many
}

export const fmt = (x: number, digits = 2) => x.toFixed(digits)
export const signed = (x: number, digits = 2) => (x >= 0 ? '+' : '') + x.toFixed(digits)

/* Пример из датасета — стоимость 95, Score 56.54. Нужен, чтобы можно было
   посмотреть работающий сценарий, не разбираясь в каталоге с нуля. */
export const EXAMPLE_DECISIONS: Decision[] = [
  { measure_id: 'M7', district_id: 'nura' },
  { measure_id: 'M8', district_id: 'nura' },
  { measure_id: 'M10', district_id: 'nura' },
  { measure_id: 'M12', district_id: null },
  { measure_id: 'M5', district_id: 'saryarka' },
]
