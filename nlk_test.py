# nlk_test.py
import os, time, requests

CERT_KEY = "53110cb199a12fd7ec327f68a6f7dbc9c120d9c22a0975b4740523fb3a89e9b0"
if not CERT_KEY:
    raise SystemExit("환경변수 NLK_CERT_KEY가 없습니다.")

url = "https://www.nl.go.kr/seoji/SearchApi.do"
params = {
    "cert_key": CERT_KEY,
    "result_style": "json",
    "page_no": 1,
    "page_size": 5,
    "title": "딥러닝"
}
headers = {"User-Agent": "Mozilla/5.0 (Local Test)"}

t0 = time.time()
try:
    # 연결 5초, 응답 10초
    r = requests.get(url, params=params, headers=headers, timeout=(5,10))
    elapsed = time.time() - t0
    print("HTTP status:", r.status_code, "| elapsed: %.2fs" % elapsed)
    # JSON 파싱
    data = r.json()
    docs = data.get("docs", [])
    print("docs count:", len(docs))
    for i, d in enumerate(docs[:3], 1):
        print(f"{i}.", d.get("TITLE", "제목 없음"))
except requests.exceptions.Timeout:
    print("⛔ Timeout: 응답이 지연되고 있습니다.")
except Exception as e:
    print("⛔ Error:", e)
