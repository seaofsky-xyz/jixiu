#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把「设备快速报修.html」构建成自托管版：static/index.html

做的事：
  1) 用同源 /api/* 顶替平台注入的 __SMART_PAGE__.database（业务代码一行不改）
  2) 登录改为服务端校验（工号 + 工号后四位），30 天免登录
  3) 企微推送从「WorkBuddy 中转」改成同源 /api/wecom/push（key 只在服务端）
  4) 页面里的正式入口地址改成本站地址

用法：
    python3 build_page.py --src ../设备快速报修.html
    python3 build_page.py --src ../设备快速报修.html --company "XX 塑业"
"""

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "static" / "index.html"

# ---------------------------------------------------------------- 替换规则
REPLACEMENTS = [
    (
        "var SITE_URL = 'https://workbuddy.link/p/FinUvbWf3zsNyYQmNT4Gru';",
        "var SITE_URL = (location.protocol + '//' + location.host + '/');",
        "页面入口地址改成本站",
    ),
    (
        "if(!/^https:\\/\\/[^/]*workbuddy\\.(link|cn)/i.test(u)) return SITE_URL;",
        "if(!/^https:/i.test(u)) return SITE_URL;",
        "入口地址白名单放开到本站 https",
    ),
    (
        "var RELAY_URL = 'https://a3ae8434ff5a8ab7a.app.workbuddy.host/?sharecode=PKZT52XPC5';",
        "var RELAY_URL = '/api/wecom/push';",
        "企微推送改走同源服务端",
    ),
    (
        "'离线模式：请在资料库中打开本页面后提交'",
        "'连不上服务器：请检查网络后重试'",
        "离线提示文案",
    ),
    (
        "'请在资料库中打开本页面'",
        "'连不上服务器，请检查网络'",
        "离线提示文案 2",
    ),
]

SHIM = r"""
<script>
/* ==================================================================
   自托管适配层（由 build_page.py 注入，请勿手改）
   - 顶替平台注入的 __SMART_PAGE__.database，业务代码零改动
   - 登录走服务端校验：工号 + 工号后四位，默认 30 天免登录
   ================================================================== */
(function(){
  var CFG = {
    company: '__COMPANY__',
    siteUrl: '__SITEURL__'
  };

  var gateResolve = null;
  var ready = new Promise(function(res){ gateResolve = res; });
  var overlay = null;

  /* ---------- 请求封装 ---------- */
  function api(method, url, body){
    return fetch(url, {
      method: method,
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body)
    }).then(function(r){
      return r.text().then(function(t){
        var j = null;
        try { j = JSON.parse(t); } catch(e) { j = null; }
        if(r.status === 401){ onUnauthorized(); throw new Error('未登录'); }
        if(!r.ok) throw new Error((j && j.error) || ('HTTP ' + r.status));
        return j || {};
      });
    });
  }

  /* ---------- 登录态写入（页面读这两个 key） ---------- */
  function seed(u){
    try{
      localStorage.setItem('wb_repair_login', JSON.stringify({
        emp: u.emp, name: u.name || '', job: u.job || '', t: new Date().getTime()
      }));
      if(u.name) localStorage.setItem('wb_repair_myname', u.name);
      if(CFG.company && !localStorage.getItem('wb_repair_company')){
        localStorage.setItem('wb_repair_company', CFG.company);
      }
    }catch(e){}
  }

  function onUnauthorized(){
    if(overlay) return;
    showLogin('');
  }

  /* ---------- 登录界面 ---------- */
  function showLogin(msg){
    if(overlay) { setMsg(msg); return; }
    var dark = false;
    try { dark = localStorage.getItem('wb_repair_dark') === '1'; } catch(e){}
    overlay = document.createElement('div');
    overlay.id = 'rsLogin';
    if(dark) overlay.className = 'rs-dark';
    overlay.innerHTML =
      '<div class="rs-box">' +
        '<div class="rs-logo">' +
          '<svg viewBox="0 0 24 24" width="34" height="34" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
            '<path d="M14.7 6.3a4 4 0 0 0 5 5l-1.9 1.9-5-5 1.9-1.9z"></path>' +
            '<path d="M11.9 8.1 4.5 15.5a2.1 2.1 0 0 0 3 3l7.4-7.4"></path>' +
          '</svg>' +
        '</div>' +
        '<div class="rs-title">设备快速报修</div>' +
        '<div class="rs-sub">请输入工号和密码（工号后四位）</div>' +
        '<input id="rsEmp" class="rs-in" type="text" inputmode="numeric" autocomplete="username" placeholder="工号，如 02004189">' +
        '<input id="rsPw" class="rs-in" type="password" inputmode="numeric" maxlength="4" autocomplete="current-password" placeholder="密码：工号后四位">' +
        '<div id="rsMsg" class="rs-msg"></div>' +
        '<button id="rsBtn" class="rs-btn" type="button">进入</button>' +
        '<div class="rs-hint">第一次进来输一次，这台手机以后自动记住</div>' +
      '</div>';
    document.body.appendChild(overlay);

    var st = document.createElement('style');
    st.textContent =
      '#rsLogin{position:fixed;inset:0;z-index:999999;background:#f4f6f8;display:flex;overflow:auto;' +
        'align-items:center;justify-content:center;padding:24px;' +
        'padding-bottom:calc(24px + env(safe-area-inset-bottom));' +
        'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif}' +
      '#rsLogin .rs-box{width:100%;max-width:360px;background:#fff;border-radius:18px;padding:28px 22px 22px;' +
        'box-shadow:0 10px 40px rgba(15,23,42,.10);text-align:center}' +
      '#rsLogin .rs-logo{width:60px;height:60px;margin:0 auto 14px;border-radius:16px;background:#e8f2ff;' +
        'color:#2563eb;display:flex;align-items:center;justify-content:center}' +
      '#rsLogin .rs-title{font-size:20px;font-weight:700;color:#0f172a;letter-spacing:.5px}' +
      '#rsLogin .rs-sub{font-size:13px;color:#64748b;margin:6px 0 20px}' +
      '#rsLogin .rs-in{display:block;width:100%;box-sizing:border-box;height:50px;margin-bottom:12px;' +
        'border:1px solid #dfe4ea;border-radius:12px;padding:0 14px;font-size:17px;color:#0f172a;background:#fbfcfd}' +
      '#rsLogin .rs-in:focus{outline:none;border-color:#2563eb;background:#fff}' +
      '#rsLogin .rs-msg{min-height:20px;font-size:13px;color:#dc2626;margin:-4px 0 8px}' +
      '#rsLogin .rs-btn{width:100%;height:50px;border:0;border-radius:12px;background:#2563eb;color:#fff;' +
        'font-size:17px;font-weight:600;cursor:pointer}' +
      '#rsLogin .rs-btn:active{background:#1d4ed8}' +
      '#rsLogin .rs-btn[disabled]{opacity:.6}' +
      '#rsLogin .rs-hint{margin-top:16px;font-size:12px;color:#94a3b8;line-height:1.6}' +
      '#rsLogin.rs-dark{background:#0b1220}' +
      '#rsLogin.rs-dark .rs-box{background:#161f2f;box-shadow:0 10px 40px rgba(0,0,0,.5)}' +
      '#rsLogin.rs-dark .rs-logo{background:#1e3a5f;color:#7eb0ff}' +
      '#rsLogin.rs-dark .rs-title{color:#e5e7eb}' +
      '#rsLogin.rs-dark .rs-sub{color:#94a3b8}' +
      '#rsLogin.rs-dark .rs-in{background:#1f2a3d;border-color:#2f3a4f;color:#e5e7eb}' +
      '#rsLogin.rs-dark .rs-in:focus{background:#243046;border-color:#3b82f6}' +
      '#rsLogin .rs-in::placeholder{color:#9aa7b8}' +
      '#rsLogin *{box-sizing:border-box}';
    document.head.appendChild(st);

    var emp = document.getElementById('rsEmp');
    var pw = document.getElementById('rsPw');
    var btn = document.getElementById('rsBtn');
    setTimeout(function(){ try{ emp.focus(); }catch(e){} }, 120);

    function submit(){
      var e = (emp.value || '').replace(/\s/g, '');
      var p = (pw.value || '').replace(/\s/g, '');
      if(!e){ setMsg('请填工号'); emp.focus(); return; }
      if(!p){ setMsg('请填密码（工号后四位）'); pw.focus(); return; }
      btn.disabled = true; btn.textContent = '正在进入…';
      api('POST', '/api/login', { emp: e, pw: p }).then(function(u){
        seed(u);
        location.reload();
      }).catch(function(err){
        btn.disabled = false; btn.textContent = '进入';
        setMsg(err && err.message ? err.message : '登录失败，请重试');
        pw.value = ''; pw.focus();
      });
    }
    function setMsg(t){
      var el = document.getElementById('rsMsg');
      if(el) el.textContent = t || '';
    }
    btn.addEventListener('click', submit);
    emp.addEventListener('keydown', function(ev){ if(ev.key === 'Enter') pw.focus(); });
    pw.addEventListener('keydown', function(ev){ if(ev.key === 'Enter') submit(); });
    if(msg) setMsg(msg);
  }
  function setMsg(t){
    var el = document.getElementById('rsMsg');
    if(el) el.textContent = t || '';
  }

  /* ---------- 启动：先确认会话 ---------- */
  fetch('/api/session', { credentials: 'same-origin' }).then(function(r){
    return r.text().then(function(t){
      var j = null; try { j = JSON.parse(t); } catch(e) { j = null; }
      return { status: r.status, j: j };
    });
  }).then(function(x){
    if(x.status === 200 && x.j && x.j.emp){
      seed(x.j);
      gateResolve(true);
    } else {
      showLogin('');
    }
  }).catch(function(){
    showLogin('连不上服务器，请检查网络');
  });

  /* ---------- 数据库适配（业务代码调这 5 个方法） ---------- */
  function wrap(fn){
    return function(){
      var args = arguments, self = this;
      return ready.then(function(){ return fn.apply(self, args); });
    };
  }
  var database = {
    getSchema: wrap(function(p){
      var id = (p && p.databaseId) || '';
      return api('GET', '/api/schema?databaseId=' + encodeURIComponent(id));
    }),
    query: wrap(function(p){ return api('POST', '/api/db/query', p || {}); }),
    addRecord: wrap(function(p){ return api('POST', '/api/db/add', p || {}); }),
    updateRecord: wrap(function(p){ return api('POST', '/api/db/update', p || {}); }),
    deleteRecord: wrap(function(p){ return api('POST', '/api/db/delete', p || {}); })
  };
  window.__SMART_PAGE__ = window.__SMART_PAGE__ || {};
  window.__SMART_PAGE__.database = database;

  /* ---------- 退出登录：同步清服务端会话 ---------- */
  document.addEventListener('click', function(e){
    var t = e.target;
    while(t && t !== document){
      if(t.id === 'pwLogoutBtn'){
        fetch('/api/logout', { method: 'POST', credentials: 'same-origin' }).then(function(){
          location.reload();
        }).catch(function(){ location.reload(); });
        return;
      }
      t = t.parentNode;
    }
  }, true);
})();
</script>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="源文件：设备快速报修.html")
    ap.add_argument("--company", default="", help="公司名（写进本机默认设置）")
    ap.add_argument("--site-url", default="", help="对外访问地址，如 https://baoxiu.example.com/")
    args = ap.parse_args()

    src = Path(args.src).expanduser().resolve()
    if not src.is_file():
        print("[x] 找不到源文件：%s" % src)
        return 1
    html = src.read_text(encoding="utf-8")
    report = []

    for old, new, label in REPLACEMENTS:
        if old in html:
            html = html.replace(old, new, 1)
            report.append(("OK", label))
        else:
            report.append(("MISS", label))

    shim = SHIM.replace("__COMPANY__", args.company or "").replace("__SITEURL__", args.site_url or "")

    idx = html.find("<script")
    if idx < 0:
        print("[x] 源文件里找不到 <script> 注入点")
        return 1
    # 插到主脚本之前，标题之后
    html = html[:idx] + shim + "\n" + html[idx:]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")

    print("=" * 56)
    print("构建完成：%s" % OUT)
    print("大小：%.1f KB" % (len(html.encode("utf-8")) / 1024))
    for s, label in report:
        print("  [%s] %s" % (s, label))
    miss = [l for s, l in report if s == "MISS"]
    if miss:
        print("\n[!] 有 %d 处替换未命中（源文件可能已改动，需人工核对）：" % len(miss))
        for l in miss:
            print("    -", l)
    # 自检
    checks = [
        ("适配层已注入", "window.__SMART_PAGE__.database = database" in html),
        ("推送走同源", "var RELAY_URL = '/api/wecom/push';" in html),
        ("入口地址本站", "location.host + '/'" in html),
        ("无平台 SDK 外链", "/page/page_comm/inject.js" not in html),
        ("无 workbuddy 中转域名", "app.workbuddy.host" not in html),
    ]
    print("\n自检：")
    bad = 0
    for label, ok in checks:
        print("  %s %s" % ("OK  " if ok else "FAIL", label))
        if not ok:
            bad += 1
    return 0 if (bad == 0 and not miss) else 2


if __name__ == "__main__":
    sys.exit(main())
