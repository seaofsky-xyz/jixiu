// 认证与会话：登录、会话读写、评分权限判定
import crypto from 'node:crypto';
import { CFG, DBS } from './config.js';
import { readTable, readSessions, writeSessions } from './store.js';

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

export async function getSession(request) {
  const token = getToken(request);
  if (!token) return null;
  const sessions = await readSessions();
  const s = sessions[token];
  if (!s) return null;
  if ((s.exp || 0) < Math.floor(Date.now() / 1000)) {
    delete sessions[token];
    await writeSessions(sessions);
    return null;
  }
  return { token, emp: s.emp || '', name: s.name || '', job: s.job || '', rate_ok: s.rate_ok || 0 };
}

export async function createSession(emp, name, job) {
  const token = crypto.randomBytes(24).toString('hex');
  const exp = Math.floor(Date.now() / 1000) + CFG.sessionDays * 86400;
  const sessions = await readSessions();
  sessions[token] = { emp, name, job, exp, rate_ok: 0 };
  await writeSessions(sessions);
  return token;
}

export async function setRateOk(token, v) {
  const sessions = await readSessions();
  if (sessions[token]) {
    sessions[token].rate_ok = v ? 1 : 0;
    await writeSessions(sessions);
  }
}

export async function deleteSession(token) {
  const sessions = await readSessions();
  if (sessions[token]) {
    delete sessions[token];
    await writeSessions(sessions);
  }
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
