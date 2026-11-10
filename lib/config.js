// 运行配置：环境变量优先，其次 data/config.json，最后默认值
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

function safeJson(s, fallback) {
  if (!s) return fallback;
  try { return JSON.parse(s); } catch (e) { return fallback; }
}

function fileCfg() {
  try {
    const p = path.join(ROOT, 'data', 'config.json');
    if (fs.existsSync(p)) return JSON.parse(fs.readFileSync(p, 'utf-8'));
  } catch (e) { /* ignore */ }
  return {};
}

const F = fileCfg();
const env = process.env;

function pick(envKey, fileVal, def) {
  if (env[envKey] !== undefined && env[envKey] !== '') return env[envKey];
  if (fileVal !== undefined && fileVal !== null && fileVal !== '') return fileVal;
  return def;
}

const ai = F.ai || {};

export const CFG = {
  company: env.JIXIU_COMPANY || F.company || '我的工厂',
  sessionDays: parseInt(env.JIXIU_SESSION_DAYS || F.sessionDays || '30', 10) || 30,
  openLogin: env.JIXIU_OPEN_LOGIN !== undefined ? env.JIXIU_OPEN_LOGIN !== '0' : true,
  adminPw: env.JIXIU_ADMIN_PW || F.adminPw || '8888',
  sessionSecret: env.JIXIU_SESSION_SECRET || F.sessionSecret || 'jixiu-repair-default-secret-2026',
  adminEmps: safeJson(env.JIXIU_ADMIN_EMPS, F.adminEmps || []),
  extraUsers: safeJson(env.JIXIU_EXTRA_USERS, F.extraUsers || []),
  wecomKey: env.JIXIU_WECOM_KEY || ((F.wecom || {}).webhookKey || ''),
  aiEnabled: env.JIXIU_AI_ENABLED !== undefined ? env.JIXIU_AI_ENABLED === '1' : !!(ai.enabled),
  aiApiKey: env.JIXIU_AI_API_KEY || ai.apiKey || '',
  aiBaseUrl: env.JIXIU_AI_BASE_URL || ai.baseUrl || 'https://api.openai.com/v1',
  aiModel: env.JIXIU_AI_MODEL || ai.model || 'gpt-4o-mini',
};

// 数据表 id 常量（与前端 index.html 一致）
export const DBS = {
  ORDER: 'bs5R43nhjgXcGROM4m0fpM',   // 工单
  SHIFT: '3JlPfR1040CXW0DT39nyeW',   // 排班管理
  STOCK: 'Q5R9iMj4TYVwHRuL6FNR4i',   // 出入库
  RAUTH: 'RateAuthTable001',         // 评分权限
};
