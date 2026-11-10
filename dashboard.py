"""Local, read-only workflow dashboard backed by the SQLite task history."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from core.context import TaskContext


PAGE = r'''<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>داشبورد ایجنت مهندسی</title><style>
:root{color-scheme:dark;--bg:#0b1020;--panel:#121a2d;--line:#25314b;--muted:#8d9bb5;--text:#edf2ff;--blue:#82aaff;--green:#42d6a4;--red:#ff7185;--amber:#ffcb70}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 10% 0%,#172344 0,transparent 45%),var(--bg);color:var(--text);font:15px/1.7 Segoe UI,Tahoma,sans-serif}
main{max-width:1180px;margin:auto;padding:36px 22px}.top{display:flex;justify-content:space-between;align-items:center;gap:18px;margin-bottom:26px}.brand{display:flex;gap:14px;align-items:center}.mark{width:46px;height:46px;border-radius:15px;display:grid;place-items:center;background:linear-gradient(145deg,#82aaff,#9e85ff);font-weight:900;color:#10182a;font-size:20px}.eyebrow{color:var(--blue);font-size:12px;letter-spacing:.08em}.title{font-size:24px;font-weight:750}.sub{color:var(--muted);font-size:13px}.refresh{background:#19243b;border:1px solid var(--line);border-radius:10px;color:var(--text);padding:9px 14px;cursor:pointer}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:20px 0}.card,.panel{background:linear-gradient(160deg,#141d32,#101728);border:1px solid var(--line);border-radius:16px}.card{padding:18px}.label{font-size:12px;color:var(--muted)}.value{font-size:29px;font-weight:750;margin-top:5px}.green{color:var(--green)}.red{color:var(--red)}.amber{color:var(--amber)}
.grid{display:grid;grid-template-columns:1.45fr 1fr;gap:14px}.panel{padding:20px}.panel h2{font-size:16px;margin:0 0 16px}.chart{height:180px;display:flex;align-items:end;justify-content:center;gap:20px;padding:12px}.bar{min-width:50px;max-width:120px;flex:1;border-radius:9px 9px 3px 3px;background:linear-gradient(0deg,#546ff0,#82aaff);position:relative;transition:height .3s}.bar.ok{background:linear-gradient(0deg,#159d83,#42d6a4)}.bar.fail{background:linear-gradient(0deg,#c44d70,#ff7185)}.bar span{position:absolute;bottom:-30px;left:0;right:0;text-align:center;color:var(--muted);font-size:12px}.legend{display:flex;justify-content:center;gap:20px;color:var(--muted);font-size:12px;margin-top:30px}.dot{display:inline-block;width:8px;height:8px;border-radius:100%;margin-left:6px;background:var(--green)}.dot.fail{background:var(--red)}
.feed{display:flex;flex-direction:column;gap:10px}.event{display:flex;gap:11px;align-items:flex-start;padding:11px;border:1px solid #202c43;border-radius:12px;background:#0f1627}.event-icon{width:30px;height:30px;display:grid;place-items:center;border-radius:9px;background:#20324a;color:var(--blue);flex:none}.event-body{min-width:0;flex:1}.event-title{font-weight:650;overflow-wrap:anywhere}.event-meta{font-size:12px;color:var(--muted);direction:ltr;text-align:right}.badge{font-size:11px;padding:2px 9px;border-radius:999px;background:#23324a;color:var(--amber);white-space:nowrap}.badge.succeeded{background:#153b38;color:var(--green)}.badge.failed{background:#422533;color:var(--red)}.empty{color:var(--muted);padding:26px;text-align:center}.foot{color:#687893;font-size:12px;margin-top:22px}
.intake{margin-bottom:14px}.form{display:grid;grid-template-columns:1fr 1.5fr auto;gap:11px;align-items:end}.field label{display:block;color:var(--muted);font-size:12px;margin-bottom:5px}.field input,.field textarea{width:100%;background:#0b1221;border:1px solid var(--line);border-radius:10px;color:var(--text);padding:11px;font:inherit;direction:ltr;text-align:left}.field textarea{height:46px;resize:vertical}.submit{border:0;border-radius:10px;padding:12px 18px;background:linear-gradient(120deg,#7598ff,#a58cff);color:#10182a;font-weight:750;cursor:pointer}.submit:disabled{opacity:.5}.notice{font-size:12px;color:var(--muted);margin-top:8px}.event{cursor:pointer}dialog{max-width:min(720px,92vw);width:100%;background:var(--panel);border:1px solid var(--line);border-radius:16px;color:var(--text);padding:22px}dialog::backdrop{background:#050914cc}.stage{padding:10px;border-bottom:1px solid var(--line)}
@media(max-width:800px){.cards{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}.form{grid-template-columns:1fr}}@media(max-width:480px){main{padding:22px 14px}.title{font-size:20px}.cards{gap:9px}.card{padding:13px}.value{font-size:24px}}
</style></head><body><main>
<header class="top"><div class="brand"><div class="mark">AE</div><div><div class="eyebrow">AUTONOMOUS ENGINEERING</div><div class="title">داشبورد اجرای پروژه</div><div class="sub">وضعیت وظایف، بررسی کد و خروجی تست‌ها</div></div></div><button class="refresh" onclick="load()">به‌روزرسانی ↻</button></header>
<section class="cards"><article class="card"><div class="label">کل وظایف</div><div class="value" id="total">—</div></article><article class="card"><div class="label">موفق</div><div class="value green" id="success">—</div></article><article class="card"><div class="label">ناموفق</div><div class="value red" id="failed">—</div></article><article class="card"><div class="label">در حال اجرا</div><div class="value amber" id="running">—</div></article></section>
<section class="panel intake"><h2>درخواست فیچر جدید</h2><form class="form" id="task-form"><div class="field"><label for="repo">مسیر مخزن Git محلی</label><input id="repo" required placeholder="D:\\Projects\\my-app"></div><div class="field"><label for="objective">توضیح فیچر یا تغییر</label><textarea id="objective" required minlength="5" maxlength="4000" placeholder="مثلاً: صفحهٔ گزارش فروش با فیلتر تاریخ اضافه کن"></textarea></div><button class="submit" id="submit" type="submit">شروع پیاده‌سازی</button></form><div class="notice" id="notice">مدل محلی Ollama · کد روی همین سیستم پردازش می‌شود · هر درخواست روی شاخهٔ جداگانه</div></section>
<section class="grid"><article class="panel"><h2>خلاصهٔ وضعیت</h2><div class="chart" id="chart"></div><div class="legend"><span><i class="dot"></i>موفق</span><span><i class="dot fail"></i>ناموفق</span><span><i class="dot" style="background:#82aaff"></i>در حال اجرا</span></div></article><article class="panel"><h2>فعالیت‌های اخیر · برای جزئیات کلیک کنید</h2><div class="feed" id="feed"><div class="empty">در حال دریافت اطلاعات…</div></div></article></section>
<dialog id="detail"><button class="refresh" onclick="document.getElementById('detail').close()">بستن</button><h2 id="detail-title"></h2><div id="detail-body"></div></dialog>
<div class="foot">اطلاعات از پایگاه محلی SQLite خوانده می‌شود · به‌روزرسانی خودکار هر ۵ ثانیه</div></main>
<script>
const faNum=n=>new Intl.NumberFormat('fa-IR').format(n);const labels={succeeded:'موفق',failed:'ناموفق',running:'در حال اجرا',pending:'در صف'};
async function load(){try{const r=await fetch('/api/tasks');if(!r.ok)throw Error();const d=await r.json(),t=d.tasks;const n={succeeded:0,failed:0,running:0,pending:0};t.forEach(x=>n[x.status]=(n[x.status]||0)+1);document.getElementById('total').textContent=faNum(t.length);document.getElementById('success').textContent=faNum(n.succeeded);document.getElementById('failed').textContent=faNum(n.failed);document.getElementById('running').textContent=faNum(n.running);const chart=document.getElementById('chart');chart.replaceChildren();for(const [k,v] of [['succeeded',n.succeeded],['failed',n.failed],['running',n.running]]){const b=document.createElement('div');b.className='bar '+(k==='succeeded'?'ok':k==='failed'?'fail':'');b.style.height=Math.max(5,t.length?150*v/t.length:5)+'px';const s=document.createElement('span');s.textContent=labels[k]+' · '+faNum(v);b.append(s);chart.append(b)}const feed=document.getElementById('feed');feed.replaceChildren();if(!t.length){const e=document.createElement('div');e.className='empty';e.textContent='هنوز وظیفه‌ای ثبت نشده است.';feed.append(e)}for(const x of t.slice(0,8)){const row=document.createElement('div');row.className='event';row.onclick=()=>showTask(x.task_id);const icon=document.createElement('div');icon.className='event-icon';icon.textContent=x.status==='succeeded'?'✓':x.status==='failed'?'!':'◷';const body=document.createElement('div');body.className='event-body';const title=document.createElement('div');title.className='event-title';title.textContent=x.objective;const meta=document.createElement('div');meta.className='event-meta';meta.textContent=x.task_id+' · '+new Date(x.updated_at).toLocaleString('fa-IR');body.append(title,meta);const badge=document.createElement('span');badge.className='badge '+x.status;badge.textContent=labels[x.status]||x.status;row.append(icon,body,badge);feed.append(row)}}catch{document.getElementById('feed').textContent='اتصال به سرور داشبورد برقرار نشد.'}}
async function showTask(id){const r=await fetch('/api/tasks/'+encodeURIComponent(id));if(!r.ok)return;const d=await r.json();document.getElementById('detail-title').textContent=d.task.objective;const box=document.getElementById('detail-body');box.replaceChildren();for(const s of d.steps){const row=document.createElement('div');row.className='stage';row.textContent=s.name+' · '+(labels[s.status]||s.status)+(s.reason?' — '+s.reason:'');box.append(row)}document.getElementById('detail').showModal()}
document.getElementById('task-form').addEventListener('submit',async e=>{e.preventDefault();const button=document.getElementById('submit'),notice=document.getElementById('notice');button.disabled=true;notice.textContent='در حال ثبت درخواست…';try{const r=await fetch('/api/tasks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({repository:document.getElementById('repo').value,objective:document.getElementById('objective').value})});const d=await r.json();if(!r.ok)throw Error(d.error||'ثبت درخواست ناموفق بود');notice.textContent='درخواست '+d.task_id+' ثبت شد؛ وضعیت اجرا به‌روز می‌شود.';document.getElementById('objective').value='';load()}catch(err){notice.textContent=err.message}finally{button.disabled=false}});
load();setInterval(load,5000);
</script></body></html>'''


def make_handler(database: str | Path, submit_task=None):
    db_path = Path(database)

    class Handler(BaseHTTPRequestHandler):
        server_version = "AutonomousDashboard/1.0"

        def _send(self, status: int, payload: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            route = urlparse(self.path).path
            if route == "/":
                return self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            if route == "/api/tasks":
                with TaskContext(db_path) as context:
                    tasks = context.list_tasks()
                body = json.dumps({"tasks": [{
                    "task_id": task.task_id, "objective": task.objective,
                    "repository": task.repository, "status": task.status.value,
                    "report": task.report, "created_at": task.created_at,
                    "updated_at": task.updated_at,
                } for task in tasks]}, ensure_ascii=False).encode("utf-8")
                return self._send(200, body, "application/json; charset=utf-8")
            if route.startswith("/api/tasks/"):
                task_id = unquote(route.removeprefix("/api/tasks/"))
                if not task_id or "/" in task_id:
                    return self._send(400, b'{"error":"invalid task id"}', "application/json")
                try:
                    with TaskContext(db_path) as context:
                        task = context.get_task(task_id)
                        steps = context.get_steps(task_id)
                except KeyError:
                    return self._send(404, b'{"error":"task not found"}', "application/json")
                body = json.dumps({
                    "task": {"task_id": task.task_id, "objective": task.objective,
                             "repository": task.repository, "status": task.status.value,
                             "report": task.report},
                    "steps": [{"name": step.name, "status": step.status.value,
                               "reason": step.reason, "payload": step.payload,
                               "started_at": step.started_at, "finished_at": step.finished_at}
                              for step in steps],
                }, ensure_ascii=False).encode("utf-8")
                return self._send(200, body, "application/json; charset=utf-8")
            self._send(404, b"Not found", "text/plain; charset=utf-8")

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/tasks" or submit_task is None:
                return self._send(404, b'{"error":"not found"}', "application/json")
            allowed_hosts = {f"127.0.0.1:{self.server.server_port}",
                             f"localhost:{self.server.server_port}",
                             f"[::1]:{self.server.server_port}"}
            if self.headers.get("Host") not in allowed_hosts:
                return self._send(403, b'{"error":"local host required"}', "application/json")
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://{host}" for host in allowed_hosts}:
                return self._send(403, b'{"error":"same-origin request required"}', "application/json")
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= 16_384:
                    raise ValueError("Request must be under 16 KiB")
                data = json.loads(self.rfile.read(length))
                objective = data.get("objective")
                repository = data.get("repository")
                if not isinstance(objective, str) or not 5 <= len(objective.strip()) <= 4000:
                    raise ValueError("Feature description must be 5 to 4000 characters")
                if not isinstance(repository, str) or not 1 <= len(repository) <= 2048:
                    raise ValueError("Enter a valid local repository path")
                local_repo = Path(repository).expanduser().resolve()
                if not local_repo.is_dir() or not (local_repo / ".git").exists():
                    raise ValueError("The selected path must be a local Git repository")
                task_id = submit_task(objective.strip(), str(local_repo))
                body = json.dumps({"task_id": task_id, "status": "running"}).encode("utf-8")
                return self._send(202, body, "application/json; charset=utf-8")
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                body = json.dumps({"error": str(exc)}).encode("utf-8")
                return self._send(400, body, "application/json; charset=utf-8")
            except Exception:
                return self._send(503, b'{"error":"could not start local agent task"}',
                                  "application/json; charset=utf-8")

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return Handler


def serve(database: str | Path, host: str = "127.0.0.1", port: int = 8765,
          submit_task=None, shutdown=None) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("The dashboard is local-only; bind to 127.0.0.1")
    server = ThreadingHTTPServer((host, port), make_handler(database, submit_task))
    print(f"Dashboard running at http://{host}:{port}/ (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if shutdown:
            shutdown()
