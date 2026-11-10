import { json } from '../../../lib/util.js';
import { getToken, setRateOk } from '../../../lib/auth.js';

export default async function onRequest(context) {
  const token = getToken(context.request);
  if (token) await setRateOk(token, 0);
  return json({ ok: true, rateOk: false });
}
