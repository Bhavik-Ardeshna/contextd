import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Keys we treat as category/label for chart slices and bars (pie, bar, line, etc.) */
const CHART_NAME_KEYS = [
  'label', 'name', 'bucket', 'bin', 'category', 'month', 'date', 'x', 'period',
  'country', 'status', 'region', 'type', 'kind',
] as const;

/** Keys we treat as numeric value for charts */
const CHART_VALUE_KEYS = [
  'value', 'count', 'cnt', 'total', 'sum', 'revenue', 'y',
  'order_count', 'num_orders', 'total_count', 'amount',
] as const;

/** Normalize a raw chart point to { name, value } for non-scatter charts. Handles various backend key names. */
export function normalizeChartPoint(
  d: Record<string, unknown>,
  index: number
): { name: string; value: number } {
  let name = '';
  for (const k of CHART_NAME_KEYS) {
    const v = d[k];
    if (v != null && v !== '') {
      name = String(v);
      break;
    }
  }
  if (!name) {
    const valueKeySet = new Set<string>(CHART_VALUE_KEYS);
    for (const k of Object.keys(d)) {
      if (valueKeySet.has(k)) continue;
      const v = d[k];
      if (typeof v === 'string' || typeof v === 'number') {
        name = String(v);
        break;
      }
    }
  }
  if (!name) name = String(index);
  if (name === 'None' || name === 'nan' || name === 'NaN' || name === 'null') name = '(missing)';

  let value = 0;
  let valueFound = false;
  const valueKeys = CHART_VALUE_KEYS as readonly string[];
  for (const k of valueKeys) {
    const v = d[k];
    if (v === undefined || v === null) continue;
    if (typeof v === 'number' && !Number.isNaN(v)) {
      value = v;
      valueFound = true;
      break;
    }
    if (typeof v === 'string' && v !== '') {
      const n = Number(v);
      if (!Number.isNaN(n)) {
        value = n;
        valueFound = true;
        break;
      }
    }
  }
  if (!valueFound) {
    const nameKeySet = new Set<string>(CHART_NAME_KEYS);
    for (const k of Object.keys(d)) {
      if (nameKeySet.has(k)) continue;
      const v = d[k];
      if (typeof v === 'number' && !Number.isNaN(v)) {
        value = v;
        break;
      }
    }
  }

  return { name, value };
}
