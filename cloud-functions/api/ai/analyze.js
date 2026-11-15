import { json, readBody } from '../../../lib/util.js';
import { getSession } from '../../../lib/auth.js';
import { readTable } from '../../../lib/store.js';
import { analyze, orderDb, orderSnapshot } from '../../../lib/ai.js';

export default async function onRequest(context) {
  const sess = await getSession(context.request);
  if (!sess) return json({ error: 'not login' }, 401);
  const body = await readBody(context.request);
  const rid = String(body.recordId || '').trim();
  if (!rid) return json({ ok: false, error: 'recordId 缺失' }, 400);
  // 前端带上工单字段快照时直接用它分析：刚提交的新单在 Blob 里可能还没传播，
  // 等几秒才查得到会让人以为「点开没反应」。快照只取白名单字段，不带图片等大字段。
  let row = null;
  if (body.order && typeof body.order === 'object' && Object.keys(body.order).length) {
    row = orderSnapshot(body.order, rid);
  } else {
    const table = await readTable(orderDb());
    row = (table.list || []).find(r => r._id === rid) || null;
  }
  if (!row) return json({ ok: false, error: '工单不存在' }, 404);
  try {
    const res = await analyze(row);
    res.ok = true;
    return json(res);
  } catch (e) {
    return json({ ok: false, error: '生成失败：' + e.message }, 500);
  }
}
