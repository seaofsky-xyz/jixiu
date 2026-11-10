import { json, readBody } from '../../../lib/util.js';
import { getToken, setRateOk } from '../../../lib/auth.js';
import { CFG } from '../../../lib/config.js';

export default async function onRequest(context) {
  const body = await readBody(context.request);
  const want = String(CFG.adminPw || '').trim();
  const got = String(body.pw || '').trim();
  if (!want) return json({ error: '服务端未设置管理密码（环境变量 JIXIU_ADMIN_PW）' }, 400);
  if (got !== want) return json({ error: '管理密码不对' }, 401);
  const token = getToken(context.request);
  const newToken = token ? setRateOk(token, 1) : null;
  const headers = { 'Content-Type': 'application/json; charset=utf-8' };
  if (newToken) headers['Set-Cookie'] = 'rs_token=' + newToken + '; Path=/; Max-Age=' + (CFG.sessionDays * 86400) + '; HttpOnly; SameSite=Lax';
  return new Response(JSON.stringify({ ok: true, rateOk: true }), { status: 200, headers });
}
