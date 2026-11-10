// 本地联调服务器：模拟 EdgeOne 的「静态托管 + cloud-functions 文件即路由」
// 用法：JIXIU_LOCAL=1 node scripts/dev-server.js
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

process.env.JIXIU_LOCAL = '1';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const DIST = path.join(ROOT, 'dist');
const CF = path.join(ROOT, 'cloud-functions');
const PORT = parseInt(process.env.PORT || '8080', 10);

function mime(file) {
  const ext = path.extname(file).toLowerCase();
  const map = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.png': 'image/png', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml',
  };
  return map[ext] || 'application/octet-stream';
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', c => chunks.push(c));
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', reject);
  });
}

function resolveHandler(pathname) {
  const rel = pathname.replace(/^\/api\//, '').replace(/\/+$/, '') || 'index';
  const direct = path.join(CF, 'api', rel + '.js');
  if (fs.existsSync(direct)) return direct;
  const index = path.join(CF, 'api', rel, 'index.js');
  if (fs.existsSync(index)) return index;
  return direct;
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  const pathname = url.pathname;
  try {
    if (pathname.startsWith('/api/')) {
      const f = resolveHandler(pathname);
      if (!fs.existsSync(f)) {
        res.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8' });
        res.end(JSON.stringify({ error: 'not found' }));
        return;
      }
      const raw = await readBody(req);
      const request = new Request(url.toString(), {
        method: req.method,
        headers: req.headers,
        body: (req.method === 'GET' || req.method === 'HEAD') ? undefined : raw,
      });
      const mod = await import(pathToFileURL(f).href + '?t=' + Date.now());
      const handler = mod.default || mod.onRequest;
      const response = await handler({ request });
      const headers = {};
      response.headers.forEach((v, k) => { headers[k] = v; });
      res.writeHead(response.status, headers);
      res.end(await response.text());
    } else {
      let file = path.join(DIST, pathname === '/' ? 'index.html' : pathname.slice(1));
      if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(DIST, 'index.html');
      res.writeHead(200, { 'Content-Type': mime(file) });
      res.end(fs.readFileSync(file));
    }
  } catch (e) {
    console.error('[dev]', pathname, e);
    res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify({ error: e.message }));
  }
});

server.listen(PORT, () => {
  console.log('本地联调已启动：http://127.0.0.1:%d/  （数据存 data-store/ 目录）', PORT);
});
