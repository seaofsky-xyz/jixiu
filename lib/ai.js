// AI 诊断分析与检修教程（规则引擎 + 可选大模型，逻辑迁移自 server.py）
import { CFG, DBS } from './config.js';
import { readTable } from './store.js';
import { AI_RULES, AI_CAT_GENERIC, AI_TUTORIALS, AI_TUT_GENERIC } from './ai-data.js';
import SCHEMA from './schema.js';

export function orderDb() {
  for (const [did, info] of Object.entries(SCHEMA)) {
    if ((info || {}).name === '工单') return did;
  }
  return DBS.ORDER;
}

function optText(dbid, field, val) {
  if (!val) return '';
  const props = ((SCHEMA[dbid] || {}).properties || []);
  for (const p of props) {
    if (p.name === field) {
      for (const o of ((p.config || {}).options || [])) {
        if (String(o.id) === String(val)) return String(o.text || '');
      }
    }
  }
  return String(val);
}

function parseDay(s) {
  const m = String(s || '').match(/(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return null;
  const t = new Date(`${m[1]}-${m[2]}-${m[3]}T00:00:00Z`).getTime();
  return Number.isNaN(t) ? null : t;
}

async function aiGather(order) {
  const od = orderDb();
  const all = await readTable(od);
  const dev = String(order['设备名称'] || '').trim();
  const part = String(order['故障部位'] || '').trim();
  const me = order._id;

  const sameDev = [];
  for (const r of all.list) {
    if (r._id === me) continue;
    if (String(r['设备名称'] || '').trim() === dev) sameDev.push(r);
  }
  const samePart = sameDev.filter(r => part && String(r['故障部位'] || '').trim() === part);
  const doneDev = sameDev.filter(r => String(r['完成日期'] || '').trim());

  const now = Date.now();
  let repeat90 = 0;
  for (const r of sameDev) {
    const d = parseDay(r['报修日期']);
    if (d && (now - d) <= 90 * 86400000) repeat90++;
  }

  const days = sameDev.map(r => parseDay(r['报修日期'])).filter(x => x).sort((a, b) => a - b);
  let avgGap = null;
  if (days.length >= 2) {
    const gaps = [];
    for (let i = 1; i < days.length; i++) {
      const g = (days[i] - days[i - 1]) / 86400000;
      if (g > 0) gaps.push(g);
    }
    if (gaps.length) avgGap = gaps.reduce((a, b) => a + b, 0) / gaps.length;
  }

  const doneSorted = doneDev
    .map(r => [parseDay(r['完成日期']) || 0, r])
    .sort((a, b) => b[0] - a[0])
    .map(x => x[1]);
  const recent = [];
  for (const r of doneSorted.slice(0, 3)) {
    const txt = String(r['维修结果'] || '').trim();
    if (txt) recent.push(`${String(r['报修日期'] || '').slice(0, 10)}：${txt.slice(0, 60)}`);
  }

  const parts = [];
  const no = String(order['工单号'] || '').trim();
  if (no) {
    const stock = await readTable(DBS.STOCK);
    for (const s of stock.list) {
      if (String(s['关联工单号'] || '').trim() === no) {
        const nm = String(s['配件名称'] || '').trim();
        if (nm) parts.push(`${nm} ×${s['数量'] || ''}${s['单位'] || ''}`);
      }
    }
  }

  return { sameDev: sameDev.length, samePart: samePart.length, repeat90, avgGap, recent, parts };
}

function aiRules(order, hist) {
  const text = [
    order['故障描述'], order['故障部位'], order['维修结果'], order['设备名称']
  ].map(x => String(x || '')).join(' ').toLowerCase();

  let causes = [], actions = [], prevents = [];
  for (const [kws, cause, acts, prev] of AI_RULES) {
    if (kws.some(k => k.toLowerCase().includes ? text.includes(k.toLowerCase()) : text.includes(k))) {
      causes.push(cause);
      actions.push(...acts);
      prevents.push(prev);
      if (causes.length >= 2) break;
    }
  }

  const cat = optText(orderDb(), '故障类别', order['故障类别']);
  if (!causes.length) {
    const g = AI_CAT_GENERIC[cat] || AI_CAT_GENERIC['机械'];
    causes = [g[0]];
    actions = [g[1]];
    prevents = [g[2]];
  }

  if (hist.repeat90 >= 2) {
    prevents.push(`该设备 90 天内已报修 ${hist.repeat90} 次（同部位 ${hist.samePart} 次），属重复故障，建议安排根因排查或技改，而不是反复换件`);
  }
  if (hist.samePart >= 3) {
    prevents.push(`同部位累计 ${hist.samePart} 单，建议核查该部位的选型/工况是否匹配`);
  }

  let summary = '已结合同设备历史工单与故障关键词给出推断，供维修参考';
  if (hist.repeat90 >= 2) {
    summary = `该设备 90 天内已重复报修 ${hist.repeat90} 次（同部位 ${hist.samePart} 次），属重复故障，建议重点做根因排查`;
  }
  return { summary, causes: causes.slice(0, 3), actions: actions.slice(0, 5), prevents: prevents.slice(0, 4) };
}

function aiText(order, summary, causes, actions, prevents, hist) {
  const od = orderDb();
  const lines = [
    '【AI 诊断分析】' + new Date().toISOString().slice(0, 16).replace('T', ' '),
    `工单：${order['工单号'] || '-'} ｜ 设备：${order['设备名称'] || '-'} ｜ 部位：${order['故障部位'] || '-'} ｜ 类别：${optText(od, '故障类别', order['故障类别']) || '-'}`,
    `现象：${order['故障描述'] || '-'}`,
    '',
    '一、原因推断',
  ];
  causes.forEach((x, i) => lines.push(`${i + 1}. ${x}`));
  lines.push('', '二、处置建议');
  actions.forEach((x, i) => lines.push(`${i + 1}. ${x}`));
  lines.push('', '三、预防建议');
  prevents.forEach((x, i) => lines.push(`${i + 1}. ${x}`));
  lines.push('', '四、历史参考');
  lines.push(`· 同设备历史 ${hist.sameDev} 单，同部位 ${hist.samePart} 单，90 天内 ${hist.repeat90} 单`);
  if (hist.avgGap) lines.push(`· 平均故障间隔 ${hist.avgGap.toFixed(1)} 天`);
  if (hist.recent.length) lines.push('· 最近处理：' + hist.recent.join('；'));
  if (hist.parts.length) lines.push('· 本次领用：' + hist.parts.join('、'));
  return lines.join('\n');
}

async function aiLlm(order, hist) {
  if (!(CFG.aiEnabled && CFG.aiApiKey)) return null;
  const base = String(CFG.aiBaseUrl || '').replace(/\/$/, '');
  const ctx = (
    `设备：${order['设备名称'] || '-'}\n部门：${order['部门'] || '-'}\n故障部位：${order['故障部位'] || '-'}\n故障类别：${optText(orderDb(), '故障类别', order['故障类别']) || '-'}\n` +
    `故障描述：${order['故障描述'] || '-'}\n维修结果：${order['维修结果'] || '-'}\n完成人：${order['完成人'] || '-'}\n` +
    `同设备历史工单 ${hist.sameDev} 单，同部位 ${hist.samePart} 单，90 天内重复 ${hist.repeat90} 次，平均故障间隔 ${hist.avgGap ? hist.avgGap.toFixed(1) : '未知'} 天。\n` +
    `最近处理：${hist.recent.join('；') || '无'}\n本次领用配件：${hist.parts.join('、') || '无'}`
  );
  const prompt = (
    '你是工厂设备维修专家。根据下面这张已完成的维修工单做故障诊断复盘。\n' + ctx +
    '\n\n只输出 JSON，不要 markdown 代码块，格式：' +
    '{"summary":"一句话结论","causes":["原因推断1","原因推断2"],"actions":["后续处置建议1","2"],"prevent":["预防措施1","2"]}' +
    '，每条 40 字以内，简体中文，结合历史重复故障给建议。'
  );
  try {
    const r = await fetch(base + '/chat/completions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + CFG.aiApiKey },
      body: JSON.stringify({
        model: CFG.aiModel,
        temperature: 0.2,
        messages: [
          { role: 'system', content: '你是严谨的工厂设备维修与预防性维护专家，回答简洁、可执行。' },
          { role: 'user', content: prompt },
        ],
      }),
    });
    if (!r.ok) return null;
    const j = await r.json();
    let txt = String(((j.choices || [{}])[0].message || {}).content || '').trim();
    const m = txt.match(/\{[\s\S]*\}/);
    const obj = JSON.parse(m ? m[0] : txt);
    if (!obj || !obj.causes) return null;
    return {
      summary: String(obj.summary || '').trim(),
      causes: (obj.causes || []).map(x => String(x).trim()).filter(Boolean).slice(0, 4),
      actions: (obj.actions || []).map(x => String(x).trim()).filter(Boolean).slice(0, 6),
      prevent: (obj.prevent || []).map(x => String(x).trim()).filter(Boolean).slice(0, 5),
    };
  } catch (e) {
    console.warn('[ai] 大模型调用失败，回落规则引擎：', e.message);
    return null;
  }
}

export async function analyze(order) {
  const hist = await aiGather(order);
  const llm = await aiLlm(order, hist);
  let engine, engineText, summary, causes, actions, prevents;
  if (llm) {
    engine = 'llm'; engineText = 'AI 大模型';
    summary = llm.summary || '分析完成';
    causes = llm.causes; actions = llm.actions; prevents = llm.prevent;
  } else {
    engine = 'rule'; engineText = '本地规则引擎（结合历史工单）';
    const r = aiRules(order, hist);
    summary = r.summary; causes = r.causes; actions = r.actions; prevents = r.prevents;
  }
  const text = aiText(order, summary, causes, actions, prevents, hist);
  return {
    engine, engineText, summary, causes, actions, prevent: prevents,
    history: {
      sameDev: hist.sameDev,
      samePart: hist.samePart,
      repeat90: hist.repeat90,
      avgGap: hist.avgGap ? Math.round(hist.avgGap * 10) / 10 : null,
      recent: hist.recent,
      parts: hist.parts,
    },
    text,
  };
}

export async function tutorial(order) {
  const text = [
    order['故障描述'], order['故障部位'], order['设备名称']
  ].map(x => String(x || '')).join(' ').toLowerCase();

  let title = '', steps = [], safety = [];
  for (const [kws, t, st, sf] of AI_TUTORIALS) {
    if (kws.some(k => text.includes(k.toLowerCase()))) {
      title = t; steps = st; safety = sf;
      break;
    }
  }
  if (!title) {
    const cat = optText(orderDb(), '故障类别', order['故障类别']);
    const g = AI_TUT_GENERIC[cat] || AI_TUT_GENERIC['机械'];
    title = g[0]; steps = g[1]; safety = g[2];
  }

  const dev = String(order['设备名称'] || '').trim();
  const part = String(order['故障部位'] || '').trim();
  const desc = String(order['故障描述'] || '').trim();
  const core = desc.replace(/[，。、；：,.;:!?！？\s]+/g, ' ').slice(0, 36).trim();
  let kw = [dev, part, core, '维修'].filter(Boolean).join(' ');
  if (kw.length > 60) kw = kw.slice(0, 60);
  const q = encodeURIComponent(kw);
  const links = [
    { name: '百度', url: 'https://www.baidu.com/s?wd=' + q },
    { name: 'B 站视频', url: 'https://search.bilibili.com/all?keyword=' + q },
    { name: '抖音', url: 'https://www.douyin.com/search/' + q },
    { name: '必应', url: 'https://cn.bing.com/search?q=' + q },
  ];
  return { title, keywords: kw, steps, safety, links, engine: 'rule', engineText: '内置检修教程库' };
}
