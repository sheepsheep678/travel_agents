/** 管理端数字格式化小工具。 */

export function pct(value: unknown, digits = 1): string {
  const n = Number(value)
  return Number.isFinite(n) ? `${(n * 100).toFixed(digits)}%` : '—'
}

export function num(value: unknown, digits = 0): string {
  const n = Number(value)
  return Number.isFinite(n) ? n.toFixed(digits) : '—'
}

export function ms(value: unknown, digits = 0): string {
  const n = Number(value)
  return Number.isFinite(n) ? `${n.toFixed(digits)} ms` : '—'
}

export function cny(value: unknown): string {
  const n = Number(value)
  return Number.isFinite(n) ? `¥${n.toFixed(4)}` : '—'
}

export function bytes(value: unknown): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export function shortSha(value: unknown): string {
  const text = String(value ?? '')
  return text ? `${text.slice(0, 12)}…` : '—'
}

export function seconds(value: unknown): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  if (n < 60) return `${n.toFixed(1)}s`
  return `${Math.floor(n / 60)}m ${Math.round(n % 60)}s`
}

/** 从 { 'mrr@10': 0.9 } 这类对象里按前缀取指标。 */
export function metric(obj: Record<string, any> | undefined, prefix: string): any {
  if (!obj) return undefined
  const key = Object.keys(obj).find((item) => item.startsWith(prefix))
  return key ? obj[key] : undefined
}
