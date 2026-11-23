"""휴대폰 브라우저로 쓰는 웹 화면.  실행: python app.py  → 같은 와이파이의 폰에서 http://<PC주소>:8000"""
import threading
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from shortsmaker.pipeline import ALL_KEYS, LABEL, make_all

ROOT = Path(__file__).parent / "jobs"
ROOT.mkdir(exist_ok=True)
JOBS: dict[str, dict] = {}
app = FastAPI()

PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>쇼핑 쇼츠 메이커</title>
<style>
:root{--bg:#f6f6f4;--card:#fff;--ink:#1d1d1b;--mute:#6b6b66;--acc:#ff5a1f;--line:#e4e4df}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--card:#1f1f1d;--ink:#f1f0ea;--mute:#a3a29b;--line:#33332f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,sans-serif}
main{max-width:520px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:24px;margin:8px 0 4px}p.sub{color:var(--mute);margin:0 0 20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px;margin-bottom:14px}
label{display:block;font-weight:600;margin:12px 0 6px}
input[type=text],input[type=url],textarea{width:100%;padding:12px;border:1px solid var(--line);border-radius:10px;background:transparent;color:var(--ink);font:inherit}
textarea{min-height:80px}.chk{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.chk label{font-weight:400;margin:0;display:flex;gap:8px;align-items:center;padding:10px;border:1px solid var(--line);border-radius:10px}
button{width:100%;padding:16px;margin-top:16px;border:0;border-radius:12px;background:var(--acc);color:#fff;font:700 18px system-ui}
button:disabled{opacity:.5}#log{white-space:pre-line;color:var(--mute)}
.out a{display:block;padding:12px;margin-top:8px;border:1px solid var(--line);border-radius:10px;color:var(--ink);text-decoration:none}
video{width:100%;border-radius:12px;margin-top:8px}small{color:var(--mute)}
</style></head><body><main>
<h1>🛍️ 쇼핑 쇼츠 메이커</h1><p class="sub">상품 영상·사진 → AI 대본 → 음성·자막 → 쇼츠 4종</p>
<form id="f" class="card">
<label>상품 영상/사진</label><input type="file" name="files" accept="video/*,image/*" multiple required>
<small>직접 찍었거나 판매자가 사용을 허락한 소스만 넣어주세요.</small>
<label>상품명</label><input type="text" name="product" required placeholder="예: 전자레인지 계란찜기">
<label>특징 메모 (선택)</label><textarea name="notes" placeholder="예: 3분이면 완성, 설거지 쉬움, 1인 가구용"></textarea>
<label>제휴 링크 (선택)</label><input type="url" name="link" placeholder="https://link.coupang.com/a/...">
<label>만들 버전</label><div class="chk">%CHECKS%</div>
<button id="go">영상 만들기</button></form>
<div class="card"><div id="log">대기 중</div><div class="out" id="out"></div></div>
<script>
const f=document.getElementById('f'),log=document.getElementById('log'),out=document.getElementById('out');
f.onsubmit=async e=>{e.preventDefault();const b=document.getElementById('go');b.disabled=true;out.innerHTML='';log.textContent='업로드 중…';
 const r=await fetch('/make',{method:'POST',body:new FormData(f)});const {id}=await r.json();
 const t=setInterval(async()=>{const s=await (await fetch('/status/'+id)).json();log.textContent=s.log.join('\\n');
  if(s.done){clearInterval(t);b.disabled=false;
   out.innerHTML=s.files.map(x=>`<a href="/file/${id}/${x.name}" download>⬇ ${x.label}</a>${x.name.endsWith('.mp4')?`<video src="/file/${id}/${x.name}" controls playsinline></video>`:''}`).join('');}},2000);};
</script></main></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    checks = "".join(f'<label><input type="checkbox" name="keys" value="{k}" checked>{LABEL[k]}</label>' for k in ALL_KEYS)
    return PAGE.replace("%CHECKS%", checks)


@app.post("/make")
async def make(files: list[UploadFile] = File(...), product: str = Form(...), notes: str = Form(""),
               link: str = Form(""), keys: list[str] = Form(ALL_KEYS)):
    jid = uuid.uuid4().hex[:10]
    d = ROOT / jid
    (d / "in").mkdir(parents=True)
    media = []
    for i, uf in enumerate(files):
        p = d / "in" / f"{i}{Path(uf.filename or 'x.mp4').suffix.lower()}"
        p.write_bytes(await uf.read())
        media.append(p)
    job = JOBS[jid] = {"log": [], "done": False, "files": []}

    def work():
        try:
            make_all(product, notes, media, d / "out", [k for k in keys if k in ALL_KEYS], link, job["log"].append)
            for k in ALL_KEYS:
                if (d / "out" / f"{k}.mp4").exists():
                    job["files"] += [{"name": f"{k}.mp4", "label": f"{LABEL[k]} 영상"},
                                     {"name": f"{k}.txt", "label": f"{LABEL[k]} 제목·설명글"}]
        except Exception as e:  # 화면에 오류 표시
            job["log"].append(f"오류: {e}")
        job["done"] = True

    threading.Thread(target=work, daemon=True).start()
    return {"id": jid}


@app.get("/status/{jid}")
def status(jid: str):
    return JSONResponse(JOBS.get(jid, {"log": ["작업을 찾을 수 없음"], "done": True, "files": []}))


@app.get("/file/{jid}/{name}")
def file(jid: str, name: str):
    p = (ROOT / jid / "out" / Path(name).name)
    return FileResponse(p, filename=p.name)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
