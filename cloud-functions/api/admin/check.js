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
  if (token) await setRateOk(token, 1);
  return json({ ok: true, rateOk: true });
}
