// 把 data-store/ 目录的内容上传到 EdgeOne Blob（一次性数据迁移用）
// 需要环境变量：
//   JIXIU_PROJECT_ID   EdgeOne 项目 ID（形如 pages-xxxxx）
//   JIXIU_API_TOKEN    EdgeOne API Token
//   JIXIU_BLOB_NS      命名空间名（默认 db）
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const DATA_STORE = path.join(ROOT, 'data-store');

const projectId = process.env.JIXIU_PROJECT_ID || '';
const token = process.env.JIXIU_API_TOKEN || '';
const ns = process.env.JIXIU_BLOB_NS || 'db';

if (!projectId || !token) {
  console.error('缺少 JIXIU_PROJECT_ID / JIXIU_API_TOKEN 环境变量');
  process.exit(1);
}

let mod = null;
for (const pkg of ['@tencent/pages-blob', '@edgeone/pages-blob']) {
  try { mod = await import(pkg); break; } catch (e) { /* 换下一个 */ }
}
if (!mod || !mod.getStore) {
  console.error('未找到 Blob SDK（@tencent/pages-blob / @edgeone/pages-blob），请先 npm install');
  process.exit(1);
}

const store = mod.getStore({ name: ns, projectId, token });

function walk(dir) {
  const out = [];
  for (const name of fs.readdirSync(dir)) {
    const full = path.join(dir, name);
    const st = fs.statSync(full);
    if (st.isDirectory()) out.push(...walk(full));
    else out.push(full);
  }
  return out;
}

let n = 0;
for (const f of walk(DATA_STORE)) {
  const rel = path.relative(DATA_STORE, f).replace(/\\/g, '/');
  const key = rel.replace(/\.json$/, '');
  const content = fs.readFileSync(f, 'utf-8');
  await store.set(key, content);
  n++;
  console.log('[upload] %s', key);
}
console.log('[upload] 完成，共 %d 个 key', n);
