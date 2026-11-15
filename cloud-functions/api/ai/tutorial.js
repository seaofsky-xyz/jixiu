import { json, readBody } from '../../../lib/util.js';
import { getSession } from '../../../lib/auth.js';
import { readTable } from '../../../lib/store.js';
import { tutorial, orderDb, orderSnapshot } from '../../../lib/ai.js';

export default async function onRequest(context) {
  const sess = await getSession(context.request);
  if (!sess) return json({ error: 'not login' }, 401);
  const body = await readBody(context.request);
  const rid = String(body.recordId || '').trim();
  if (!rid) return json({ ok: false, error: 'recordId 缺失' }, 400);
  let row = null;
  if (body.order && typeof body.order === 'object' && Object.keys(body.order).length) {
    row = orderSnapshot(body.order, rid);
  } else {
    const table = await readTable(orderDb());
    row = (table.list || []).find(r => r._id === rid) || null;
  }
  if (!row) return json({ ok: false, error: '工单不存在' }, 404);
  try {
    const res = await tutorial(row);
    res.ok = true;
    return json(res);
  } catch (e) {
    return json({ ok: false, error: '生成失败：' + e.message }, 500);
  }
}
