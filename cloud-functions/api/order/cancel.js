// 报修单撤销 / 恢复的专用接口。
// 不用通用删除接口：撤销是「软撤销」，保留工单记录与撤销人/时间，随时可恢复，
// 且权限一律在服务端判定（前端显示的按钮只是提示，不能作为凭据）。
import { json, readBody } from '../../../lib/util.js';
import { getSession, canCancelOrder, isAdmin, isOrderOwner } from '../../../lib/auth.js';
import { DBS } from '../../../lib/config.js';
import { readTable, writeTable } from '../../../lib/store.js';

const F_STATUS = '撤销状态';
const F_BY = '撤销人';
const F_AT = '撤销时间';

export default async function onRequest(context) {
  const sess = await getSession(context.request);
  if (!sess) return json({ error: 'not login' }, 401);
  const body = await readBody(context.request);
  const rid = String(body.recordId || '').trim();
  const mode = body.mode === 'restore' ? 'restore' : 'cancel';
  if (!rid) return json({ ok: false, error: 'recordId 缺失' }, 400);

  const table = await readTable(DBS.ORDER);
  const idx = table.list.findIndex(r => r._id === rid);
  if (idx < 0) return json({ ok: false, error: '工单不存在' }, 404);
  const row = table.list[idx];

  if (!(await canCancelOrder(sess, row))) {
    return json({ ok: false, error: '没有权限撤销这条报修单：只有报修人本人、管理员或授权人可以' }, 403);
  }

  const who = String(sess.name || '').trim() || String(sess.emp || '').trim() || '管理员';
  const scope = isAdmin(sess) ? '管理员' : (isOrderOwner(sess, row) ? '报修人本人' : '授权人');
  if (mode === 'restore') {
    delete row[F_STATUS];
    delete row[F_BY];
    delete row[F_AT];
  } else {
    row[F_STATUS] = '已撤销';
    row[F_BY] = who + '（' + scope + '）';
    row[F_AT] = new Date().toISOString();
  }
  table.list[idx] = row;
  await writeTable(DBS.ORDER, table);
  return json({ ok: true, mode, recordId: rid, by: row[F_BY] || '', at: row[F_AT] || '' });
}
