import { json, readBody } from '../../../lib/util.js';
import { CFG } from '../../../lib/config.js';
import { getSession } from '../../../lib/auth.js';

export default async function onRequest(context) {
  const sess = await getSession(context.request);
  if (!sess) return json({ error: 'not login' }, 401);
  const key = String(CFG.wecomKey || '').trim();
  if (!key) return json({ ok: false, error: '服务端未配置企微机器人 key' }, 400);
  const body = await readBody(context.request);
  const msg = body.msg || body;
  try {
    const r = await fetch('https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=' + encodeURIComponent(key), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(msg),
    });
    const j = await r.json();
    if (j.errcode === 0) return json({ ok: true, wecom: j });
    return json({ ok: false, error: j.errmsg || '企微返回错误', wecom: j }, 502);
  } catch (e) {
    return json({ ok: false, error: '企微接口不可达：' + e.message }, 502);
  }
}
