import { json } from '../../lib/util.js';
import { getSession, rateAllowed, isAdmin, cancelListAllowed } from '../../lib/auth.js';

export default async function onRequest(context) {
  const s = await getSession(context.request);
  if (!s) return json({ error: 'not login' }, 401);
  const rateOk = await rateAllowed(s);
  const adminOk = isAdmin(s);
  const cancelOk = adminOk || await cancelListAllowed(s);
  return json({ emp: s.emp, name: s.name, job: s.job, rateOk, adminOk, cancelOk });
}
