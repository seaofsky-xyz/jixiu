import { json } from '../../lib/util.js';
import { readTable } from '../../lib/store.js';
import { orderDb } from '../../lib/ai.js';

export default async function onRequest() {
  const t = await readTable(orderDb());
  return json({ ok: true, service: 'jixiu', records: (t.list || []).length });
}
