import { json, readBody } from '../../../lib/util.js';
import { CFG } from '../../../lib/config.js';
import { getSession } from '../../../lib/auth.js';
import crypto from 'node:crypto';

// 兼容粘完整 Webhook URL、只粘 key、或带空格换行，统一成纯 key
function normKey(raw) {
  let s = String(raw || '').replace(/\s/g, '');
  if (!s) return '';
  const i = s.indexOf('key=');
  if (i >= 0) s = s.slice(i + 4);
  const j = s.indexOf('&');
  if (j >= 0) s = s.slice(0, j);
  return s;
}

// 企业微信「图片消息」要求：base64 不含 data: 前缀，md5 是图片二进制的 MD5。
// md5 浏览器里不好算（WebCrypto 不支持 MD5），统一放到云端补算，前端只传压缩后的图片。
function toImageMsg(raw) {
  let b64 = String(raw || '').replace(/\s/g, '');
  const mark = b64.indexOf('base64,');
  if (b64.indexOf('data:') === 0 && mark >= 0) b64 = b64.slice(mark + 7);
  if (!b64) return null;
  const buf = Buffer.from(b64, 'base64');
  if (!buf.length) return null;
  if (buf.length > 2 * 1024 * 1024) return { tooLarge: true };  // 企微上限 2MB
  return {
    msgtype: 'image',
    image: { base64: b64, md5: crypto.createHash('md5').update(buf).digest('hex') },
  };
}

export default async function onRequest(context) {
  const sess = await getSession(context.request);
  if (!sess) return json({ error: 'not login' }, 401);
  const body = await readBody(context.request);
  let msg = body.msg || body;
  if (body.image) {
    const im = toImageMsg(body.image);
    if (!im) return json({ ok: false, error: '图片数据为空或格式不对' }, 400);
    if (im.tooLarge) return json({ ok: false, error: '图片超过 2MB，企业微信不接受，请换一张或压缩后再发' }, 400);
    msg = im;
  }
  // 优先用页面里填的机器人 key（每台设备可指定自己的群），其次用服务端环境变量
  const key = normKey(body.key) || normKey(CFG.wecomKey);
  if (!key) return json({ ok: false, error: '未配置企业微信群机器人：请在企业微信群添加「群机器人」后，把 Webhook 地址填到系统设置里，或配置到服务端环境变量' }, 400);
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
