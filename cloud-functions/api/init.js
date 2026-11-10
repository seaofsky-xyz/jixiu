// 数据初始化：部署后访问一次，把内置的初始数据快照写入 EdgeOne Blob
// 在 Makers Functions 内直接调 SDK（零配置，自动鉴权，无需 projectId / token）
// 幂等：已有数据的表会被跳过，不会覆盖云端已有数据
import { readTable, writeTable, readMeta, writeMeta } from '../../lib/store.js';
import { SEED_TABLES, SEED_META } from '../../lib/seed-data.js';

export default async function onRequest() {
  const results = {};
  for (const [dbid, table] of Object.entries(SEED_TABLES)) {
    const cur = await readTable(dbid);
    if (cur && Array.isArray(cur.list) && cur.list.length) {
      results[dbid] = '已存在（' + cur.list.length + ' 条），跳过';
    } else {
      await writeTable(dbid, table);
      results[dbid] = '已初始化 ' + (table.list ? table.list.length : 0) + ' 条';
    }
  }
  const m = await readMeta();
  if (!m || !Object.keys(m).length) {
    await writeMeta(SEED_META || {});
    results['_sys/meta'] = '已初始化';
  }
  return new Response(JSON.stringify({ ok: true, results }), {
    status: 200,
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
  });
}
