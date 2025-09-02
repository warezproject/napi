import json
import re
from pathlib import Path
import requests
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="국가정보정책협의회 TEST", layout="wide")

# 0) 쿼리스트링에서 검색어 읽기
kw = st.query_params.get("kw", [""])[0].strip()

# 1) 전남연구원 로컬 JSON 로드(존재/레코드 수 확인)
jndi_json_path = Path("static/전남연구원_자료.json")
jndi_exists = jndi_json_path.exists()
jndi_total = 0
jndi_results = []

if jndi_exists:
    try:
        jndi_all = json.loads(jndi_json_path.read_text(encoding="utf-8"))
        jndi_total = len(jndi_all)
        if kw:
            low_kw = kw.casefold()
            for rec in jndi_all:
                # 열 이름이 '서명 '처럼 공백이 붙어 있는 경우 대비
                # 후보 키들을 순회
                for k in ("서명", "서명 ", " 제목", "Title", "title"):
                    if k in rec and isinstance(rec[k], str):
                        title = rec[k].casefold()
                        if low_kw in title:
                            jndi_results.append(rec)
                            break
    except Exception as e:
        st.warning(f"전남연구원 JSON 읽기 오류: {e}")
else:
    st.info("static/전남연구원_자료.json 파일을 찾을 수 없습니다. 이름/경로를 확인해 주세요.")

# 2) NLK(API) 서버사이드 호출 (Secrets에 NLK_CERT_KEY 필요)
nlk_docs = []
if kw:
    try:
        CERT_KEY = st.secrets["NLK_CERT_KEY"]
        url = "https://www.nl.go.kr/seoji/SearchApi.do"
        params = {
            "cert_key": CERT_KEY,
            "result_style": "json",
            "page_no": 1,
            "page_size": 10,
            "title": kw
        }
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        nlk_docs = data.get("docs", []) or []
    except KeyError:
        st.error("Secrets에 NLK_CERT_KEY가 없습니다. Settings → Secrets에 NLK_CERT_KEY를 추가해 주세요.")
    except Exception as e:
        st.warning(f"국립중앙도서관 API 호출 오류: {e}")

# 3) index.html 읽기
html_path = Path("index.html")
if not html_path.exists():
    st.error("index.html 파일이 없습니다. 저장소 루트에 index.html을 두세요.")
    st.stop()

html = html_path.read_text(encoding="utf-8")

# 3-1) 사용자가 섞어 썼을 수 있는 Tailwind CDN 마크다운 표기 교정
html = html.replace("[https://cdn.tailwindcss.com](https://cdn.tailwindcss.com/)", "https://cdn.tailwindcss.com")
html = html.replace("[https://cdn.tailwindcss.com](https://cdn.tailwindcss.com)", "https://cdn.tailwindcss.com")

# 3-2) 상대경로를 /app/static/ 절대경로로 자동 치환
# - img/src, a/href, fetch(...) 등에서 '파일명.확장자'만 적은 경우 대응
# - 이미 http(s):// 또는 / 로 시작하는 것은 유지
def _to_static_abs(m):
    url = m.group(1)
    if url.startswith(("http://", "https://", "/", "data:")):
        return m.group(0)  # 그대로
    # 파일명 또는 하위폴더 상대경로 → /app/static/ 접두
    return m.group(0).replace(url, f"/app/static/{url}")

# img/src
html = re.sub(r'src=["\']([^"\']+)["\']', _to_static_abs, html, flags=re.IGNORECASE)
# a/href (외부 링크는 그대로)
html = re.sub(r'href=["\']([^"\']+)["\']', lambda m: m.group(0) if m.group(1).startswith(("http://","https://","/")) else m.group(0).replace(m.group(1), f"/app/static/{m.group(1)}"), html, flags=re.IGNORECASE)
# fetch('...') / fetch("...")
html = re.sub(r'fetch\((["\'])([^"\']+)\1\)', lambda m: m.group(0) if m.group(2).startswith(("http://","https://","/")) else f'fetch("/app/static/{m.group(2)}")', html, flags=re.IGNORECASE)

# 4) 결과 주입 & searchBooks 오버라이드 스크립트(일반 문자열로!)
inject = """
<script>
  // 서버에서 주입한 검색 상태/결과(키는 내려가지 않습니다)
  window.__PRELOADED__ = {
    keyword: %(KW)s,
    jndi: %(JNDI)s,
    nlk: %(NLK)s,
    debug: {
      jndi_file_exists: %(JEXISTS)s,
      jndi_total_records: %(JTOTAL)s
    }
  };

  // searchBooks 오버라이드: 쿼리스트링만 갱신 → 앱 재실행
  window.searchBooks = function() {
    const input = document.getElementById('searchInput');
    const nextKw = (input ? input.value : '').trim();
    const url = new URL(window.location.href);
    if (nextKw) { url.searchParams.set('kw', nextKw); }
    else { url.searchParams.delete('kw'); }
    if (window.parent && window.parent !== window) {
      window.parent.location.href = url.toString();
    } else {
      window.location.href = url.toString();
    }
  };

  // 최초 렌더(주입 데이터로 그리기)
  document.addEventListener('DOMContentLoaded', function() {
    const preload = window.__PRELOADED__ || {};
    const kw = preload.keyword || '';
    const jndiContainer = document.getElementById('jndiResults');
    const nlkContainer  = document.getElementById('nlkResults');
    const input = document.getElementById('searchInput');
    if (input && kw) input.value = kw;

    if (jndiContainer) jndiContainer.innerHTML = '';
    if (nlkContainer)  nlkContainer.innerHTML  = '';

    // 전남연구원 카드
    (preload.jndi || []).forEach(function(book){
      const card = document.createElement('div');
      card.className = 'bg-white shadow p-4 rounded border border-green-400';
      const title = book['서명'] || book['서명 '] || book['Title'] || book['title'] || '';
      const author = book['저자'] || '정보 없음';
      const pub = book['발행자'] || '정보 없음';
      const year = book['발행년도'] || '정보 없음';
      const regno = book['등록번호'] || '';
      card.innerHTML = `
        <h3 class="text-lg font-bold mb-1">${title}</h3>
        <p class="text-sm text-gray-700">저자: ${author}</p>
        <p class="text-sm text-gray-700">발행자: ${pub}</p>
        <p class="text-sm text-gray-700">발행년도: ${year}</p>
        <p class="text-sm text-gray-500">등록번호: ${regno}</p>
        <span class="inline-block mt-2 text-xs text-green-600 font-medium">출처: 전남연구원</span>
      `;
      jndiContainer && jndiContainer.appendChild(card);
    });

    // 국립중앙도서관 카드
    const docs = preload.nlk || [];
    if (docs.length === 0) {
      if (kw && nlkContainer) {
        nlkContainer.innerHTML = '<p class="text-center col-span-full text-gray-500">검색 결과가 없습니다.</p>';
      }
      return;
    }
    docs.forEach(function(book){
      const isbn = book.ISBN || '';
      const linkUrl = 'https://www.nl.go.kr/search/searchResult.jsp?category=total&kwd=' + encodeURIComponent(book.TITLE || '');
      const imageUrl = isbn ? ('https://image.aladin.co.kr/product/' + isbn.slice(-3) + '/' + isbn.slice(-5) + 'cover.jpg') : '';
      const card = document.createElement('a');
      card.className = 'bg-white shadow p-4 rounded hover:ring-2 ring-blue-400 transition';
      card.href = linkUrl;
      card.target = '_blank';
      card.innerHTML = `
        ${imageUrl ? '<img src="' + imageUrl + '" alt="도서 표지" class="w-full h-48 object-contain mb-3"/>' : ''}
        <h3 class="text-lg font-bold mb-1">${book.TITLE || '제목 없음'}</h3>
        <p class="text-sm text-gray-700">저자: ${book.AUTHOR || '정보 없음'}</p>
        <p class="text-sm text-gray-700">출판사: ${book.PUBLISHER || '정보 없음'}</p>
        <p class="text-sm text-gray-700">발행년도: ${book.PUBLISH_YEAR || '정보 없음'}</p>
        <p class="text-sm text-gray-500">ISBN: ${isbn}</p>
      `;
      nlkContainer && nlkContainer.appendChild(card);
    });

    // 간단 디버그(원하면 주석 해제)
    // console.log('PRELOADED.debug =', preload.debug);
  });
</script>
"""

# 주입 데이터(JSON 직렬화) 삽입
inject = inject % {
    "KW": json.dumps(kw, ensure_ascii=False),
    "JNDI": json.dumps(jndi_results, ensure_ascii=False),
    "NLK": json.dumps(nlk_docs, ensure_ascii=False),
    "JEXISTS": json.dumps(jndi_exists),
    "JTOTAL": json.dumps(jndi_total),
}

# </body> 직전 삽입
if "</body>" in html:
    html = html.replace("</body>", inject + "\n</body>")
else:
    html += inject

# 렌더
components.html(html, height=1600, scrolling=True)