from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import os, time, requests

app = FastAPI()
# 필요 시 Streamlit 도메인만 허용하도록 origins를 좁히세요.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 예: ["https://your-app.streamlit.app"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

NLK_CERT_KEY = os.environ["NLK_CERT_KEY"]
NLK_URL = "https://www.nl.go.kr/seoji/SearchApi.do"

# 아주 단순한 메모리 캐시(제목 기준, 10분 TTL)
_cache = {}
TTL = 600  # seconds

def cache_get(key):
    v = _cache.get(key)
    if not v: return None
    ts, data = v
    if time.time() - ts > TTL:
        _cache.pop(key, None)
        return None
    return data

def cache_set(key, data):
    _cache[key] = (time.time(), data)

@app.get("/nlk")
def nlk_proxy(title: str = Query(""), page_no: int = 1, page_size: int = 10):
    key = f"{title}|{page_no}|{page_size}"
    hit = cache_get(key)
    if hit is not None:
        return hit

    params = {
        "cert_key": NLK_CERT_KEY,
        "result_style": "json",
        "page_no": page_no,
        "page_size": page_size,
        "title": title,
    }
    headers = {"User-Agent": "Mozilla/5.0 (NLK Proxy)"}
    r = requests.get(NLK_URL, params=params, headers=headers, timeout=(5, 10))
    data = r.json()
    cache_set(key, data)
    return data

@app.get("/health")
def health():
    return {"ok": True}
