// 种子数据导入：把 data/seed.json 导入到数据后端（本地文件或 Blob）
// 用法：node scripts/seed.js [--blob]
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
process.env.JIXIU_LOCAL = process.env.JIXIU_LOCAL || '1';

const { readTable, writeTable } = await import('../lib/store.js');
const { normValue, propsOf } = await import('../lib/util.js');

const seed = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'seed.json'), 'utf-8'));
let total = 0;
for (const [dbid, rows] of Object.entries(seed)) {
  const table = await readTable(dbid);
  const props = propsOf(dbid);
  for (const r of rows || []) {
    const rid = String(r._id || r.record_id || crypto.randomBytes(12).toString('hex'));
    const data = {};
    for (const [k, v] of Object.entries(r)) {
      if (k === '_id' || k === 'record_id') continue;
      data[k] = normValue(props[k], v);
    }
    data._id = rid;
    // 去重：同 id 覆盖
    const idx = table.list.findIndex(x => x._id === rid);
    if (idx >= 0) table.list[idx] = data; else table.list.push(data);
    total++;
  }
  await writeTable(dbid, table);
  console.log('[seed] 表 %s：%d 条', dbid, table.list.length);
}
console.log('[seed] 完成，共 %d 条', total);
