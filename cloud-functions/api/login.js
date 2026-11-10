import { readBody } from '../../lib/util.js';
import { findMember, createSession } from '../../lib/auth.js';
import { CFG } from '../../lib/config.js';

export default async function onRequest(context) {
  const body = await readBody(context.request);
  const emp = String(body.emp || '').trim();
  const pw = String(body.pw || '').trim();
  if (!emp || !pw) return new Response(JSON.stringify({ error: '请填工号和密码' }), { status: 400, headers: { 'Content-Type': 'application/json; charset=utf-8' } });

  let m = await findMember(emp);
  if (!m) {
    if (CFG.openLogin && /^\d{4,12}$/.test(emp)) {
      m = { emp, name: '', job: '' };
    } else {
      return new Response(JSON.stringify({ error: '工号 ' + emp + ' 不存在，请联系管理员' }), { status: 400, headers: { 'Content-Type': 'application/json; charset=utf-8' } });
    }
  }
  if (pw !== emp.slice(-4)) {
    return new Response(JSON.stringify({ error: '密码不对：请填工号的后四位' }), { status: 400, headers: { 'Content-Type': 'application/json; charset=utf-8' } });
  }
  const token = await createSession(m.emp, m.name, m.job);
  const cookie = `rs_token=${token}; Path=/; Max-Age=${CFG.sessionDays * 86400}; HttpOnly; SameSite=Lax`;
  return new Response(JSON.stringify({ ok: true, emp: m.emp, name: m.name, job: m.job }), {
    status: 200,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'Set-Cookie': cookie },
  });
}
