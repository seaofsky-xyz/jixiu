// 构建脚本：把前端静态页复制到 dist，并把 data/schema.json 内联成 lib/schema.js
// 供 EdgeOne Pages 的 npm run build 调用
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

function ensure(dir) {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

// 1. 复制前端静态页 → dist/
const distDir = path.join(ROOT, 'dist');
const staticDir = path.join(ROOT, 'static');
ensure(distDir);
const html = fs.readFileSync(path.join(staticDir, 'index.html'));
fs.writeFileSync(path.join(distDir, 'index.html'), html);
console.log('[build] 已生成 dist/index.html（%d 字节）', html.length);

// 2. 内联 schema → lib/schema.js
const schemaPath = path.join(ROOT, 'data', 'schema.json');
if (fs.existsSync(schemaPath)) {
  const schema = JSON.parse(fs.readFileSync(schemaPath, 'utf-8'));
  const out = '// 本文件由 scripts/build.js 从 data/schema.json 自动生成，请勿手改\n'
    + 'export default ' + JSON.stringify(schema) + ';\n';
  fs.writeFileSync(path.join(ROOT, 'lib', 'schema.js'), out);
  console.log('[build] 已生成 lib/schema.js（%d 张表）', Object.keys(schema).length);
} else {
  console.warn('[build] 未找到 data/schema.json，跳过 schema 生成');
}

console.log('[build] 完成');
