import type { Decision, Meta } from './api'

export const DIR_COLORS: Record<string, string> = {
  transport: 'var(--t)', ecology: 'var(--e)', social: 'var(--s)', safety: 'var(--b)', services: 'var(--c)',
}
export const DIR_HEX: Record<string, string> = {
  transport: '#4cc2ff', ecology: '#3ecf8e', social: '#b48cff', safety: '#ff8a5c', services: '#f5d76e',
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
export const fmt = (x: number, digits = 2) => x.toFixed(digits)
export const signed = (x: number, digits = 2) => (x >= 0 ? '+' : '') + x.toFixed(digits)
