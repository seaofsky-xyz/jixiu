import { json, readBody } from '../../../lib/util.js';
import { getSession } from '../../../lib/auth.js';
import * as db from '../../../lib/db.js';

export default async function onRequest(context) {
  const sess = await getSession(context.request);
  if (!sess) return json({ error: 'not login' }, 401);
  const body = await readBody(context.request);
  try {
    return json(await db.del(body));
  } catch (e) {
    return json({ error: e.error || 'error' }, e.status || 500);
  }
}
