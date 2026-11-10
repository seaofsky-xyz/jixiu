// 数据访问层：EdgeOne Blob 存储（云端运行时）与本地文件（本地联调）双后端
// 数据组织（单命名空间，用 key 分目录）：
//   table/{dbid}        -> 某张业务表的全量记录 { list:[...], created_at, updated_at }
//   _sys/sessions       -> 会话表 { token: {emp,name,job,exp,rate_ok} }
//   _sys/meta           -> 键值元数据 { k: v }
// 注意：Blob SDK 必须用静态 import（EdgeOne 构建器按静态 import 收集依赖并打包 node_modules）
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { getStore } from '@edgeone/pages-blob';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const DATA_DIR = process.env.JIXIU_DATA_DIR || path.join(ROOT, 'data-store');
const NAMESPACE = process.env.JIXIU_BLOB_NS || 'db';

let _backend = null;

// ---------- 后端实现 ----------

function createFileBackend(dir) {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  return {
    async read(key) {
      const f = path.join(dir, key + '.json');
      if (!fs.existsSync(f)) return null;
      try { return JSON.parse(fs.readFileSync(f, 'utf-8')); }
      catch (e) { return null; }
    },
    async write(key, value) {
      const f = path.join(dir, key + '.json');
      fs.mkdirSync(path.dirname(f), { recursive: true });
      fs.writeFileSync(f, JSON.stringify(value));
    },
    async remove(key) {
      const f = path.join(dir, key + '.json');
      if (fs.existsSync(f)) fs.unlinkSync(f);
    }
  };
}

function createBlobBackend(store) {
  return {
    async read(key) {
      const v = await store.get(key, { type: 'json' });
      return v == null ? null : v;
    },
    async write(key, value) {
      await store.set(key, JSON.stringify(value));
    },
    async remove(key) {
      await store.delete(key);
    }
  };
}

function resolveBackend() {
  if (_backend) return _backend;
  // 云端（EdgeOne Makers Functions 内）：getStore 零配置、自动鉴权，首次调用自动创建命名空间
  if (!process.env.JIXIU_LOCAL) {
    try {
      _backend = createBlobBackend(getStore(NAMESPACE));
      return _backend;
    } catch (e) {
      console.warn('[store] Blob 初始化失败，回落本地文件后端：', e && e.message);
    }
  }
  _backend = createFileBackend(DATA_DIR);
  return _backend;
}

// ---------- 业务读写 ----------

export async function readTable(dbid) {
  const be = await resolveBackend();
  const v = await be.read('table/' + dbid);
  if (v && Array.isArray(v.list)) return v;
  return { list: [], created_at: '', updated_at: '' };
}

export async function writeTable(dbid, table) {
  const be = await resolveBackend();
  table.created_at = table.created_at || new Date().toISOString();
  table.updated_at = new Date().toISOString();
  await be.write('table/' + dbid, table);
  return table;
}

export async function readSessions() {
  const be = await resolveBackend();
  const v = await be.read('_sys/sessions');
  return (v && typeof v === 'object') ? v : {};
}

export async function writeSessions(sessions) {
  const be = await resolveBackend();
  await be.write('_sys/sessions', sessions);
  return sessions;
}

export async function readMeta() {
  const be = await resolveBackend();
  const v = await be.read('_sys/meta');
  return (v && typeof v === 'object') ? v : {};
}

export async function writeMeta(meta) {
  const be = await resolveBackend();
  await be.write('_sys/meta', meta);
  return meta;
}
