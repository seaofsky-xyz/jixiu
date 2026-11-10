import { json } from '../../lib/util.js';
import SCHEMA from '../../lib/schema.js';

export default async function onRequest(context) {
  const url = new URL(context.request.url);
  const dbid = url.searchParams.get('databaseId') || '';
  const info = SCHEMA[dbid];
  if (!info) return json({ properties: [] });
  return json({ databaseId: dbid, name: info.name || '', properties: info.properties || [] });
}
