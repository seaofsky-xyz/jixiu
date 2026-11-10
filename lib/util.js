// 通用工具：HTTP 响应、请求解析、排序键、字段规范化
import SCHEMA from './schema.js';

export function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
  });
}

export async function readBody(request) {
  try {
    const text = await request.text();
    if (!text) return {};
    return JSON.parse(text);
  } catch (e) {
    return {};
  }
}

// 排序键（对应 Python sort_key）
export function sortKey(v) {
  if (v === null || v === undefined || v === '') return [0, 0, ''];
  if (typeof v === 'boolean') return [1, v ? 1 : 0, ''];
  if (typeof v === 'number') return [1, v, ''];
  return [2, 0, String(v)];
}

// 页面写入格式 {text:...}/{select:...} → 裸值
export function unwrap(v) {
  if (v && typeof v === 'object' && !Array.isArray(v)) {
    for (const k of ['text', 'select', 'number', 'date', 'checkbox']) {
      if (k in v) return v[k];
    }
    if ('multi_select' in v) return v.multi_select;
    return null;
  }
  return v;
}

// 把「选项文本」统一换成「选项 id」（对应 Python norm_value）
export function normValue(prop, val) {
  if (val === null || val === undefined) return null;
  const t = (prop || {}).type;
  const opts = ((prop || {}).config || {}).options || [];
  if (t === 'select') {
    const ids = new Set(opts.map(o => String(o.id)));
    if (typeof val === 'string' && ids.has(val)) return val;
    for (const o of opts) if (o.text === val) return o.id;
    return val;
  }
  if (t === 'multi_select') {
    if (!Array.isArray(val)) return val;
    const ids = new Set(opts.map(o => String(o.id)));
    return val.map(v => {
      if (typeof v === 'string' && ids.has(v)) return v;
      for (const o of opts) if (o.text === v) return o.id;
      return v;
    });
  }
  return val;
}

export function propsOf(dbid) {
  const list = ((SCHEMA[dbid] || {}).properties || []);
  const map = {};
  for (const p of list) map[p.name] = p;
  return map;
}

// 排序比较：direction 为 'ascending' 或 'descending'
export function compareRows(a, b, prop, desc) {
  const ka = sortKey(a[prop]);
  const kb = sortKey(b[prop]);
  let c = 0;
  if (ka[0] !== kb[0]) c = ka[0] - kb[0];
  else if (ka[1] !== kb[1]) c = (ka[1] > kb[1] ? 1 : ka[1] < kb[1] ? -1 : 0);
  else c = String(ka[2]).localeCompare(String(kb[2]), 'zh');
  return desc ? -c : c;
}
