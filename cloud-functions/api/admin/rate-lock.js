import { getToken, setRateOk } from '../../../lib/auth.js';
import { CFG } from '../../../lib/config.js';

export default async function onRequest(context) {
  const token = getToken(context.request);
  const newToken = token ? setRateOk(token, 0) : null;
  const headers = { 'Content-Type': 'application/json; charset=utf-8' };
  if (newToken) headers['Set-Cookie'] = 'rs_token=' + newToken + '; Path=/; Max-Age=' + (CFG.sessionDays * 86400) + '; HttpOnly; SameSite=Lax';
  return new Response(JSON.stringify({ ok: true, rateOk: false }), { status: 200, headers });
}
