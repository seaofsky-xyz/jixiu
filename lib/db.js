// 通用数据库 CRUD（对应 server.py 的 _query/_add/_update/_delete）
import crypto from 'node:crypto';
import { readTable, writeTable } from './store.js';
import { compareRows, normValue, propsOf, unwrap } from './util.js';
import { rateAllowed } from './auth.js';
import { orderDb } from './ai.js';

const RATE_FIELDS = ['评分', '评分人', '评分日期', '评分备注'];
const RATE_AUTH_DB = 'RateAuthTable001';

export async function query(body, sess) {
  const dbid = String(body.databaseId || '');
  if (!dbid) return { results: [], hasMore: false, nextCursor: null };

  const table = await readTable(dbid);
  let rows = table.list || [];

  // 评分数据与评分名单：没有权限的人，服务端直接不给
  const allowed = await rateAllowed(sess);
  if (!allowed) {
    if (dbid === orderDb()) {
      rows = rows.map(r => {
        const out = { ...r };
        for (const k of RATE_FIELDS) delete out[k];
        return out;
      });
    } else if (dbid === RATE_AUTH_DB) {
      rows = [];
    }
  }

  const sorts = body.sorts || [];
  for (const s of [...sorts].reverse()) {
    const prop = s.property;
    const desc = (s.direction || 'ascending') === 'descending';
    rows.sort((a, b) => compareRows(a, b, prop, desc));
  }

  let off = parseInt(body.startCursor || '0', 10);
  if (Number.isNaN(off)) off = 0;
  let size = parseInt(body.pageSize || '100', 10);
  if (Number.isNaN(size)) size = 100;
  size = Math.max(1, Math.min(size, 500));

  const page = rows.slice(off, off + size);
  const more = (off + size) < rows.length;
  return {
    results: page,
    hasMore: more,
    nextCursor: more ? String(off + size) : null,
  };
}

export async function add(body) {
  const dbid = String(body.databaseId || '');
  if (!dbid) throw { status: 400, error: 'databaseId 缺失' };
  const props = propsOf(dbid);
  const data = {};
  for (const [k, v] of Object.entries(body.properties || {})) {
    data[k] = normValue(props[k], unwrap(v));
  }
  const rid = crypto.randomBytes(12).toString('hex');
  const now = new Date().toISOString();
  const table = await readTable(dbid);
  data._id = rid;
  table.list.push(data);
  await writeTable(dbid, table);
  return { id: rid };
}

export async function update(body, sess) {
  const dbid = String(body.databaseId || '');
  const rid = String(body.recordId || '');
  if (!dbid || !rid) throw { status: 400, error: 'databaseId / recordId 缺失' };
  const propsIn = body.properties || {};
  const allowed = await rateAllowed(sess);
  if (dbid === orderDb() && !allowed && Object.keys(propsIn).some(k => RATE_FIELDS.includes(k))) {
    throw { status: 403, error: '没有评分权限' };
  }
  const props = propsOf(dbid);
  const table = await readTable(dbid);
  const idx = table.list.findIndex(r => r._id === rid);
  if (idx < 0) throw { status: 404, error: '记录不存在' };
  for (const [k, v] of Object.entries(propsIn)) {
    table.list[idx][k] = normValue(props[k], unwrap(v));
  }
  await writeTable(dbid, table);
  return { id: rid };
}

export async function del(body) {
  const dbid = String(body.databaseId || '');
  const rid = String(body.recordId || '');
  if (!dbid || !rid) throw { status: 400, error: 'databaseId / recordId 缺失' };
  const table = await readTable(dbid);
  table.list = table.list.filter(r => r._id !== rid);
  await writeTable(dbid, table);
  return { ok: true };
}
