import { getToken, deleteSession } from '../../lib/auth.js';

export default async function onRequest(context) {
  const token = getToken(context.request);
  if (token) await deleteSession(token);
  return new Response(JSON.stringify({ ok: true }), {
    status: 200,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Set-Cookie': 'rs_token=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax',
    },
  });
}
