// 认证与会话：无状态签名 token（HMAC-SHA256）
// 会话不再存 Blob（Blob 是最终一致性的对象存储，写入后约 5-6 秒才可见，
// 导致登录后立即 401）。改为「签名 token 放进 cookie」，登录/改权限即时生效。
import crypto from 'node:crypto';
import { CFG, DBS } from './config.js';
import { readTable } from './store.js';

function b64url(buf) {
  return Buffer.from(buf).toString('base64url');
}

function signToken(payload) {
  const data = b64url(JSON.stringify(payload));
  const sig = crypto.createHmac('sha256', CFG.sessionSecret).update(data).digest('base64url');
  return data + '.' + sig;
}

function verifyToken(token) {
  try {
    const i = token.lastIndexOf('.');
    if (i <= 0) return null;
    const data = token.slice(0, i);
    const sig = token.slice(i + 1);
    const expect = crypto.createHmac('sha256', CFG.sessionSecret).update(data).digest('base64url');
    if (sig !== expect) return null;
    const payload = JSON.parse(Buffer.from(data, 'base64url').toString('utf-8'));
    if (!payload || typeof payload !== 'object') return null;
    if ((payload.exp || 0) < Math.floor(Date.now() / 1000)) return null;
    return payload;
  } catch (e) {
    return null;
  }
}

export function getToken(request) {
  const cookie = request.headers.get('cookie') || '';
  for (const part of cookie.split(';')) {
    const i = part.indexOf('=');
    if (i >= 0 && part.slice(0, i).trim() === 'rs_token') {
      return part.slice(i + 1).trim();
    }
  }
  return null;
}

export function getSession(request) {
  const token = getToken(request);
  if (!token) return null;
  const p = verifyToken(token);
  if (!p) return null;
  return { token, emp: p.emp || '', name: p.name || '', job: p.job || '', rate_ok: p.rateOk || 0 };
}

export function createSession(emp, name, job) {
  const exp = Math.floor(Date.now() / 1000) + CFG.sessionDays * 86400;
  return signToken({ emp, name, job, rateOk: 0, exp });
}

// 更新评分权限位：返回重新签发后的新 token（由调用方写回 Set-Cookie）
export function setRateOk(token, v) {
  const p = verifyToken(token);
  if (!p) return null;
  p.rateOk = v ? 1 : 0;
  return signToken(p);
}

// 无状态：登出由前端清 cookie 完成
export function deleteSession(token) {
  return;
}

export async function findMember(emp) {
  emp = String(emp || '').trim();
  for (const u of CFG.extraUsers || []) {
    if (String(u.emp || '').trim() === emp) return { emp, name: u.name || '', job: u.job || '' };
  }
  const table = await readTable(DBS.SHIFT);
  for (const r of table.list) {
    if (String(r['工号'] || '').trim() === emp) return { emp, name: r['姓名'] || '', job: r['岗位'] || '' };
  }
  return null;
}

export async function rateAllowed(sess) {
  if (!sess) return false;
  if ((sess.rate_ok || 0) === 1) return true;
  const emp = String(sess.emp || '').trim();
  const name = String(sess.name || '').trim();
  if (!emp && !name) return false;
  const table = await readTable(DBS.RAUTH);
  for (const r of table.list) {
    const e = String(r['工号'] || '').trim();
    const n = String(r['姓名'] || '').trim();
    if (emp && e && e === emp) return true;
    if (name && n && n === name) return true;
  }
  return false;
}
