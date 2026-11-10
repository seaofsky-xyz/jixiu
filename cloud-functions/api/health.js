import { json } from '../../lib/util.js';
import { readTable } from '../../lib/store.js';
import { orderDb } from '../../lib/ai.js';
import { CFG } from '../../lib/config.js';

export default async function onRequest() {
  const t = await readTable(orderDb());
  const k = String(CFG.wecomKey || '').trim();
  return json({
    ok: true,
    service: 'jixiu',
    records: (t.list || []).length,
    wecom: k ? ('ok:' + k.slice(-4)) : 'none',
  });
}
