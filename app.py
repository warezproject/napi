import json
from pathlib import Path
import requests
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="국가정보정책협의회 TEST", layout="wide")

# 1) 검색어(kw) 읽기
kw = st.query_params.get("kw", [""])[0].strip()

# 2) 전남연구원 로컬 JSON 검색
jndi_json_path = Path("static/전남연구원.json")
jndi_results = []
if jndi_json_path.exists() and kw:
    try:
        jndi_all = json.loads(jndi_json_path.read_text(encoding="utf-8"))
        # '서명'에 부분일치 (대소문자 구분 없이)
        low_kw = kw.lower()
        for rec in jndi_all:
            title = (rec.get("서명") or "").lower()
            if low_kw in title:
                jndi_results.append(rec)
    except Exception as e:
        st.warning(f"전남연구원 JSON 읽기 오류: {e}")

# 3) NLK(API) 서버사이드 호출 (키는 Secrets에 보관)
nlk_docs = []
if kw:
    try:
        CERT_KEY = st.secrets["NLK_CERT_KEY"]  # Streamlit Secrets에서 읽음
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
        st.error("Secrets에 NLK_CERT_KEY가 설정되지 않았습니다. 앱 설정(Secrets)에 NLK_CERT_KEY를 추가해 주세요.")
    except Exception as e:
        st.warning(f"국립중앙도서관 API 호출 오류: {e}")

# 4) index.html 읽기
html_path = Path("index.html")
if not html_path.exists():
    st.error("index.html 파일이 없습니다. 저장소 루트에 index.html을 두세요.")
    st.stop()

html = html_path.read_text(encoding="utf-8")

# 5) 결과 주입 & searchBooks 오버라이드 스크립트 삽입
inject = f"""
<script>
  // 서버에서 주입한 검색 결과 (키는 절대 노출되지 않음)
  window.__PRELOADED__ = {{
    keyword: {json.dumps(kw, ensure_ascii=False)},
    jndi: {json.dumps(jndi_results, ensure_ascii=False)},
    nlk: {json.dumps(nlk_docs, ensure_ascii=False)}
  }};

  // ① 기존 HTML의 searchBooks를 오버라이드:
  //    - 버튼 클릭 시 쿼리스트링만 갱신 → Streamlit이 재실행되며 서버가 새 결과를 주입
  window.searchBooks = function() {{
    const input = document.getElementById('searchInput');
    const nextKw = (input ? input.value : '').trim();
    const url = new URL(window.location.href);
    if (nextKw) {{
      url.searchParams.set('kw', nextKw);
    }} else {{
      url.searchParams.delete('kw');
    }}
    // Streamlit 상위 프레임 주소를 갱신 (이 iframe만 바꾸면 안 되므로 parent 사용)
    if (window.parent && window.parent !== window) {{
      window.parent.location.href = url.toString();
    }} else {{
      window.location.href = url.toString();
    }}
  }};

  // ② 첫 로드 시 주입 데이터로 그대로 그리기 (원본 HTML의 렌더 로직을 재사용)
  document.addEventListener('DOMContentLoaded', function() {{
    const preload = window.__PRELOADED__ || {{}};
    const kw = preload.keyword || '';
    const jndiContainer = document.getElementById('jndiResults');
    const nlkContainer = document.getElementById('nlkResults');
    const input = document.getElementById('searchInput');
    if (input && kw) input.value = kw;

    if (!jndiContainer || !nlkContainer) return;
    jndiContainer.innerHTML = '';
    nlkContainer.innerHTML = '';

    // 전남연구원 카드
    (preload.jndi || []).forEach(book => {{
      const card = document.createElement('div');
      card.className = 'bg-white shadow p-4 rounded border border-green-400';
      card.innerHTML = `
        <h3 class="text-lg font-bold mb-1">\${book['서명']||''}</h3>
        <p class="text-sm text-gray-700">저자: \${book['저자']||'정보 없음'}</p>
        <p class="text-sm text-gray-700">발행자: \${book['발행자']||'정보 없음'}</p>
        <p class="text-sm text-gray-700">발행년도: \${book['발행년도']||'정보 없음'}</p>
        <p class="text-sm text-gray-500">등록번호: \${book['등록번호']||''}</p>
        <span class="inline-block mt-2 text-xs text-green-600 font-medium">출처: 전남연구원</span>
      `;
      jndiContainer.appendChild(card);
    }});

    // 국립중앙도서관 카드
    const docs = preload.nlk || [];
    if (docs.length === 0) {{
      if (kw) {{
        nlkContainer.innerHTML = '<p class="text-center col-span-full text-gray-500">검색 결과가 없습니다.</p>';
      }}
      return;
    }}
    docs.forEach(book => {{
      const isbn = book.ISBN || '';
      const linkUrl = 'https://www.nl.go.kr/search/searchResult.jsp?category=total&kwd=' + encodeURIComponent(book.TITLE || '');
      const imageUrl = isbn ? ('https://image.aladin.co.kr/product/' + isbn.slice(-3) + '/' + isbn.slice(-5) + 'cover.jpg') : '';
      const card = document.createElement('a');
      card.className = 'bg-white shadow p-4 rounded hover:ring-2 ring-blue-400 transition';
      card.href = linkUrl;
      card.target = '_blank';
      card.innerHTML = `
        \${imageUrl ? '<img src="' + imageUrl + '" alt="도서 표지" class="w-full h-48 object-contain mb-3"/>' : ''}
        <h3 class="text-lg font-bold mb-1">\${book.TITLE || '제목 없음'}</h3>
        <p class="text-sm text-gray-700">저자: \${book.AUTHOR || '정보 없음'}</p>
        <p class="text-sm text-gray-700">출판사: \${book.PUBLISHER || '정보 없음'}</p>
        <p class="text-sm text-gray-700">발행년도: \${book.PUBLISH_YEAR || '정보 없음'}</p>
        <p class="text-sm text-gray-500">ISBN: \${isbn}</p>
      `;
      nlkContainer.appendChild(card);
    }});
  }});
</script>
"""

# </body> 직전에 주입 (없으면 맨 끝에 붙임)
if "</body>" in html:
    html = html.replace("</body>", inject + "\n</body>")
else:
    html += inject

# 6) iframe로 렌더
components.html(html, height=1600, scrolling=True)
