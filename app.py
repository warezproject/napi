import json
from pathlib import Path
from urllib.parse import quote_plus
import re
import xml.etree.ElementTree as ET
import requests
import streamlit as st

# -----------------------------
# 기본 설정
# -----------------------------
st.set_page_config(page_title="국가정보정책협의회 TEST", layout="wide")
st.title("국가정보정책협의회 TEST")
st.caption("전남연구원 로컬 데이터 + 국립중앙도서관 Open API")

# 페이지네이션 간격 좁히기 (한 번만 선언)
st.markdown("""
<style>
div[data-testid="jndi_pager"]  .stRadio > div,
div[data-testid="nlk_pager"]   .stRadio > div,
div[data-testid="aladin_pager"] .stRadio > div { gap: 4px !important; }

div[data-testid="jndi_pager"]  label,
div[data-testid="nlk_pager"]   label,
div[data-testid="aladin_pager"] label { padding: 2px 6px !important; border: 1px solid #ddd; border-radius: 6px; }

div[data-testid="jndi_pager"]  input:checked + div,
div[data-testid="nlk_pager"]   input:checked + div,
div[data-testid="aladin_pager"] input:checked + div { font-weight: 700; }
</style>
""", unsafe_allow_html=True)

# -----------------------------
# 세션 상태 초기화
# -----------------------------
if "query" not in st.session_state:
    st.session_state.query = ""   # 마지막 검색어
if "jndi_page" not in st.session_state:
    st.session_state.jndi_page = 1
if "nlk_page" not in st.session_state:
    st.session_state.nlk_page = 1
if "aladin_page" not in st.session_state:
    st.session_state.aladin_page = 1


# -----------------------------
# 입력 UI
# -----------------------------
with st.form("search_form", clear_on_submit=False):
    # 입력창 value를 세션값으로 유지
    kw = st.text_input("도서 제목을 입력하세요", value=st.session_state.query, placeholder="예: 딥러닝, LLM, 인공지능 …")
    submitted = st.form_submit_button("검색")

if submitted:
    st.session_state.query = kw.strip()
    st.session_state.jndi_page = 1
    st.session_state.nlk_page = 1
    st.rerun()

# -----------------------------
# 검색어 없는 경우 초기 화면
# -----------------------------
if not st.session_state.query:
    st.info("상단 입력창에 검색어를 입력하고 **검색** 버튼을 눌러주세요.")
    st.stop()

# -----------------------------
# 여기부터는 항상 세션의 query 사용
# -----------------------------
PAGE_SIZE = 10
active_kw = st.session_state.query

# -----------------------------
# 전남연구원 로컬 JSON 로딩
# -----------------------------
@st.cache_data(show_spinner=False)
def load_jndi_json_best_effort():
    """여러 후보 파일명 시도 + 존재/건수 메타 반환"""
    candidates = [
        Path("static/전남연구원.json"),
    ]
    for p in candidates:
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    # dict 안에서 리스트를 찾아봄
                    for k in ("rows", "data", "items", "list", "docs"):
                        if isinstance(data.get(k), list):
                            return data[k], {"exists": True, "count": len(data[k]), "path": str(p)}
                    return [], {"exists": True, "count": 0, "path": str(p)}
                elif isinstance(data, list):
                    return data, {"exists": True, "count": len(data), "path": str(p)}
                else:
                    return [], {"exists": True, "count": 0, "path": str(p)}
            except Exception as e:
                return [], {"exists": True, "count": 0, "path": str(p), "error": str(e)}
    return [], {"exists": False, "count": 0, "path": None}

def search_jndi(records, keyword: str):
    if not keyword:
        return []
    key_candidates = ("서명", "서명 ", "서명(국문)", "자료명", "제목", "Title", "title", "TITLE")
    low_kw = keyword.casefold().strip()
    matched = []
    for rec in records:
        for k in key_candidates:
            v = rec.get(k)
            if isinstance(v, str) and low_kw in v.casefold().strip():
                matched.append(rec)
                break
    return matched

# -----------------------------
# NLK Open API 헬퍼
# -----------------------------
_ISBN_RE = re.compile(r"[0-9Xx\-]{10,17}")

def _get_first(rec: dict, keys: tuple) -> str:
    if not isinstance(rec, dict):
        return ""
    for k in keys:
        for cand in (k, k.lower(), k.upper(), k.capitalize()):
            v = rec.get(cand)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return ""

def _get_by_substring(rec: dict, substrings: tuple) -> str:
    if not isinstance(rec, dict):
        return ""
    for key, val in rec.items():
        if not isinstance(key, str):
            continue
        lower = key.lower()
        if any(sub in lower for sub in substrings):
            if isinstance(val, str) and val.strip():
                return val.strip()
    return ""

def _extract_isbn(rec: dict) -> str:
    isbn = _get_first(rec, ("ISBN", "isbn", "isbn13", "ISBN13", "ea_isbn", "EA_ISBN", "set_isbn", "SET_ISBN"))
    if not isbn:
        isbn = _get_by_substring(rec, ("isbn",))
    if not isbn:
        return ""
    m = _ISBN_RE.findall(isbn)
    if not m:
        return ""
    candidates = [re.sub(r"[^0-9Xx]", "", s) for s in m]
    for c in candidates:
        if len(c) == 13:
            return c
    for c in candidates:
        if len(c) == 10:
            return c
    return candidates[0] if candidates else isbn

def _extract_cn(rec: dict) -> str:
    cn = _get_first(rec, ("CN", "cn", "control_no", "CONTROL_NO", "controlNo", "CONTROLNO", "docid", "DOCID", "doc_id", "DOC_ID", "bib_id", "BIB_ID"))
    if cn:
        return str(cn).strip()
    cn = _get_by_substring(rec, ("control", "cn"))
    return str(cn).strip() if cn else ""

def _extract_detail_link(rec: dict) -> str:
    # 1) detail_link / link / url 류 우선
    detail = _get_first(rec, ("detail_link", "DETAIL_LINK", "link", "LINK", "url", "URL"))
    if not detail:
        detail = _get_by_substring(rec, ("detail_link", "link", "url"))
    if detail:
        if detail.startswith("/"):
            return f"https://www.nl.go.kr{detail}"
        if detail.startswith("http"):
            return detail
    # 2) 보강 생성: ISBN → CN
    isbn = _extract_isbn(rec)
    if isbn:
        return f"https://www.nl.go.kr/search/SearchDetail.do?isbn={quote_plus(isbn)}"
    cn = _extract_cn(rec)
    if cn:
        return f"https://www.nl.go.kr/search/SearchDetail.do?cn={quote_plus(cn)}"
    # 3) 최후 폴백: 제목검색
    title = _get_first(rec, ("title_info", "TITLE", "title"))
    if title:
        return f"https://www.nl.go.kr/search/searchResult.jsp?category=total&kwd={quote_plus(title)}"
    return "https://www.nl.go.kr"

# -----------------------------
# (중요) ISBN으로 2차 XML 조회하여 detail_link 보강
# -----------------------------
@st.cache_data(show_spinner=False)
def fetch_detail_link_by_isbn(isbn: str, api_key: str, timeout: int = 12) -> str:
    """
    OpenAPI XML (detailSearch=true & isbnOp=isbn & isbnCode=...)로 재조회하여
    <result><item><detail_link>의 첫 값을 절대 URL로 반환. 실패 시 빈 문자열.
    """
    if not isbn or not api_key:
        return ""
    url = "https://www.nl.go.kr/NL/search/openApi/search.do"
    # XML 응답 강제: apiType=xml
    params = {
        "key": api_key,
        "detailSearch": "true",
        "isbnOp": "isbn",
        "isbnCode": isbn,
        "apiType": "xml",
        "pageNum": 1,
        "pageSize": 10
    }
    headers = {"User-Agent": "Mozilla/5.0 (Streamlit OpenAPI XML Client)"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        r.raise_for_status()
        # XML 파싱
        root = ET.fromstring(r.text)
        # XPath 유연 탐색
        items = root.findall(".//result/item")
        for it in items:
            dl = it.findtext("detail_link", default="").strip()
            if dl:
                return f"https://www.nl.go.kr{dl}" if dl.startswith("/") else dl
        return ""
    except Exception:
        return ""

def _is_search_fallback(link: str) -> bool:
    """현재 링크가 searchResult.jsp 형태의 폴백인지 검사"""
    if not link:
        return True
    return "searchResult.jsp" in link

def _enrich_links_with_isbn(records: list, api_key: str) -> list:
    """
    각 레코드의 DETAIL_LINK가 폴백(searchResult.jsp)이거나 비었고,
    ISBN이 있으면 2차 XML 호출로 detail_link 보강.
    """
    if not isinstance(records, list) or not api_key:
        return records
    out = []
    for rec in records:
        link = rec.get("DETAIL_LINK") or ""
        isbn = (rec.get("ISBN") or "").strip()
        if isbn and _is_search_fallback(link):
            fixed = fetch_detail_link_by_isbn(isbn, api_key)
            if fixed:
                rec = {**rec, "DETAIL_LINK": fixed}
        out.append(rec)
    return out

# -----------------------------
# 알라딘 API 호출
# -----------------------------
def call_aladin_api(keyword: str, page_num: int = 1, page_size: int = 10):
    """
    알라딘 상품 검색 API (ItemSearch)
    - XML로 받아 파싱
    - page_num은 1부터 시작
    반환: (docs, totalResults)
    """
    if not keyword:
        return [], 0

    ttbkey = st.secrets.get("ALADIN_TTB_KEY")
    if not ttbkey:
        st.error("Secrets에 ALADIN_TTB_KEY가 없습니다.")
        return [], 0

    url = "http://www.aladin.co.kr/ttb/api/ItemSearch.aspx"
    params = {
        "ttbkey": ttbkey,
        "Query": keyword,
        "QueryType": "Keyword",     # 제목+저자
        "MaxResults": page_size,    # 페이지 당 개수(최대 50)
        "start": page_num,          # 1-based page
        "SearchTarget": "Book",     # 도서
        "output": "xml",            # XML 파싱 안전
        "Version": "20131101",
        "Cover": "MidBig",          # 표지 크기(선택)
        "includeKey": 0
    }
    headers = {"User-Agent": "Mozilla/5.0 (Streamlit Aladin Client)"}

    try:
        r = requests.get(url, params=params, headers=headers, timeout=12)
        r.raise_for_status()
        root = ET.fromstring(r.text)

        # totalResults / itemsPerPage / startIndex 등 상단 메타
        total_str = root.findtext(".//totalResults") or "0"
        try:
            total = int(total_str)
        except:
            total = 0

        docs = []
        for item in root.findall(".//item"):
            title  = (item.findtext("title") or "").strip() or "제목 없음"
            link   = (item.findtext("link") or "").strip()
            author = (item.findtext("author") or "").strip() or "정보 없음"
            pub    = (item.findtext("publisher") or "").strip() or "정보 없음"
            date   = (item.findtext("pubDate") or "").strip()
            isbn13 = (item.findtext("isbn13") or "").strip()
            cover  = (item.findtext("cover") or "").strip()
            rank   = (item.findtext("customerReviewRank") or "").strip()

            docs.append({
                "TITLE": title,
                "LINK": link,
                "AUTHOR": author,
                "PUBLISHER": pub,
                "PUBDATE": date,
                "ISBN13": isbn13,
                "COVER": cover,
                "RATING": rank,
            })

        return docs, total

    except Exception as e:
        st.warning(f"알라딘 API 호출 오류: {e}")
        return [], 0

# -----------------------------
# 국립중앙도서관 API 호출
# -----------------------------
import xml.etree.ElementTree as ET
import re

def call_aladin_api(keyword: str, page_num: int = 1, page_size: int = 10, query_type: str = "Keyword"):
    """
    알라딘 상품 검색 API (ItemSearch)
    - XML 기본 네임스페이스(xmlns)를 안전하게 처리
    - page_num: 1-based (알라딘 API 'start'와 동일)
    - query_type: "Keyword" | "Title" | "Author" ...
    반환: (docs, totalResults)
    """
    if not keyword:
        return [], 0

    ttbkey = st.secrets.get("ALADIN_TTB_KEY")
    if not ttbkey:
        st.error("Secrets에 ALADIN_TTB_KEY가 없습니다.")
        return [], 0

    # 알라딘은 공식 가이드상 http 엔드포인트 표기.
    # 일부 환경에서 http가 막히면 프록시를 고려하세요.
    url = "http://www.aladin.co.kr/ttb/api/ItemSearch.aspx"
    params = {
        "ttbkey": ttbkey,
        "Query": keyword,
        "QueryType": query_type,     # 예: "Title" (요청하신 예시), 기본은 "Keyword"
        "MaxResults": page_size,     # 1~50
        "start": page_num,           # 1-based
        "SearchTarget": "Book",
        "output": "xml",
        "Version": "20131101",
        "Cover": "MidBig",
    }
    headers = {"User-Agent": "Mozilla/5.0 (Streamlit Aladin Client)"}

    try:
        r = requests.get(url, params=params, headers=headers, timeout=12)
        r.raise_for_status()
        text = r.text

        # --- 1) 네임스페이스-aware 파싱 시도 ---
        root = ET.fromstring(text)

        # 루트 네임스페이스 추출 (예: {http://www.aladin.co.kr/ttb/apiguide.aspx})
        m = re.match(r'^\{(.*)\}', root.tag)
        ns_uri = m.group(1) if m else None
        ns = {"a": ns_uri} if ns_uri else None

        def _find(path):
            if ns:
                return root.find(path, ns)
            return root.find(path)

        def _findall(path):
            if ns:
                return root.findall(path, ns)
            return root.findall(path)

        # totalResults
        total_node = _find(".//a:totalResults" if ns else ".//totalResults")
        total_str = total_node.text.strip() if (total_node is not None and total_node.text) else "0"
        try:
            total = int(total_str)
        except:
            total = 0

        # item 노드들
        items = _findall(".//a:item" if ns else ".//item")

        # --- 2) 네임스페이스로도 못 찾으면(예외 케이스), 폴백: 네임스페이스 제거 후 재파싱 ---
        if not items:
            no_ns_text = re.sub(r'\sxmlns="[^"]+"', "", text, count=1)  # 기본 xmlns 제거
            root2 = ET.fromstring(no_ns_text)
            total_str = (root2.findtext(".//totalResults") or "0").strip()
            try:
                total = int(total_str)
            except:
                total = 0
            items = root2.findall(".//item")
            # 이때부터는 root2에서 직접 텍스트를 꺼내자
            def _txt2(elem, tag):
                t = elem.findtext(tag)
                return (t or "").strip()
            docs = []
            for it in items:
                docs.append({
                    "TITLE":   _txt2(it, "title") or "제목 없음",
                    "LINK":    _txt2(it, "link"),
                    "AUTHOR":  _txt2(it, "author") or "정보 없음",
                    "PUBLISHER": _txt2(it, "publisher") or "정보 없음",
                    "PUBDATE": _txt2(it, "pubDate"),
                    "ISBN13":  _txt2(it, "isbn13"),
                    "COVER":   _txt2(it, "cover"),
                    "RATING":  _txt2(it, "customerReviewRank"),
                })
            return docs, total

        # --- 3) 정상(네임스페이스-aware) 경로 ---
        def _txt(elem, tag):
            if ns:
                t = elem.findtext(f"a:{tag}", namespaces=ns)
            else:
                t = elem.findtext(tag)
            return (t or "").strip()

        docs = []
        for it in items:
            docs.append({
                "TITLE":    _txt(it, "title") or "제목 없음",
                "LINK":     _txt(it, "link"),
                "AUTHOR":   _txt(it, "author") or "정보 없음",
                "PUBLISHER":_txt(it, "publisher") or "정보 없음",
                "PUBDATE":  _txt(it, "pubDate"),
                "ISBN13":   _txt(it, "isbn13"),
                "COVER":    _txt(it, "cover"),
                "RATING":   _txt(it, "customerReviewRank"),
            })

        return docs, total

    except Exception as e:
        st.warning(f"알라딘 API 호출/파싱 오류: {e}")
        return [], 0



# -----------------------------
# 알라딘 커버 (옵션)
# -----------------------------
def aladin_cover_from_isbn(isbn: str):
    if not isbn:
        return ""
    return f"https://image.aladin.co.kr/product/{isbn[-3:]}/{isbn[-5:]}cover.jpg"

# -----------------------------
# 데이터 로드
# -----------------------------
jndi_all, jndi_meta = load_jndi_json_best_effort()

# -----------------------------
# 검색 실행 (세션의 query 기준준)
# -----------------------------
PAGE_SIZE = 10
active_kw = st.session_state.query  # 세션의 검색어로 항상 렌더링

# ===== 데이터 준비 =====
# 전남연구원
jndi_all, jndi_meta = load_jndi_json_best_effort()
jndi_hits = search_jndi(jndi_all, active_kw)
jndi_total = len(jndi_hits)
jndi_total_pages = max(1, (jndi_total + PAGE_SIZE - 1) // PAGE_SIZE)
jndi_page = st.session_state.jndi_page
j_start = (jndi_page - 1) * PAGE_SIZE
j_end   = j_start + PAGE_SIZE
jndi_page_data = jndi_hits[j_start:j_end]

# 국립중앙도서관
nlk_page = st.session_state.nlk_page
nlk_docs, nlk_total = call_nlk_api(active_kw, page_num=nlk_page, page_size=PAGE_SIZE)
nlk_total_pages = max(1, (nlk_total + PAGE_SIZE - 1) // PAGE_SIZE)

# 알라딘
ALADIN_PAGE_SIZE = 10
aladin_page = st.session_state.aladin_page
aladin_docs, aladin_total = call_aladin_api(active_kw, page_num=aladin_page, page_size=ALADIN_PAGE_SIZE)
aladin_total_pages = max(1, (aladin_total + ALADIN_PAGE_SIZE - 1) // ALADIN_PAGE_SIZE)

# -----------------------------
# 3열 레이아웃 (왼/JNDI · 중/NLK · 오/알라딘)
# -----------------------------
st.write("---")
col_left, col_center, col_right = st.columns([1, 1, 1])

# ===== 왼쪽: 전남연구원 =====
with col_left:
    st.subheader("전남연구원")
    st.caption(f"총 {jndi_total}건 · {jndi_page}/{jndi_total_pages}페이지")
    if jndi_page_data:
        for b in jndi_page_data:
            with st.container(border=True):
                title = b.get('서명') or b.get('서명 ') or b.get('서명(국문)') or b.get('Title') or b.get('제목') or ''
                st.markdown(f"**{title}**")
                st.caption(
                    f"저자: {b.get('저자','정보 없음')} · "
                    f"발행자: {b.get('발행자','정보 없음')} · "
                    f"발행년도: {b.get('발행년도','정보 없음')}"
                )
    else:
        st.info("검색 결과가 없습니다.")

    # 하단 페이지네이션 (가로, 촘촘)
    if jndi_total_pages > 1:
        start_page = max(1, jndi_page - 2)
        end_page   = min(jndi_total_pages, jndi_page + 2)
        opts       = list(range(start_page, end_page + 1))
        st.markdown('<div data-testid="jndi_pager">', unsafe_allow_html=True)
        sel = st.radio("JNDI 페이지", opts, index=opts.index(jndi_page),
                       horizontal=True, label_visibility="collapsed",
                       key=f"jndi_radio_{active_kw}")
        st.markdown('</div>', unsafe_allow_html=True)
        if sel != jndi_page:
            st.session_state.jndi_page = int(sel)
            st.rerun()

# ===== 가운데: 국립중앙도서관 =====
with col_center:
    st.subheader("국립중앙도서관")
    st.caption(f"총 {nlk_total}건 · {nlk_page}/{nlk_total_pages}페이지")
    if nlk_docs:
        for d in nlk_docs:
            with st.container(border=True):
                title = d.get("TITLE", "제목 없음")
                link  = d.get("DETAIL_LINK") or ""
                st.markdown(f"**[{title}]({link})**" if link else f"**{title}**")
                st.caption(
                    f"저자: {d.get('AUTHOR','정보 없음')} · "
                    f"출판사: {d.get('PUBLISHER','정보 없음')} · "
                    f"발행년도: {d.get('PUBLISH_YEAR','정보 없음')}"
                )
    else:
        st.info("검색 결과가 없습니다.")

    if nlk_total_pages > 1:
        start_page = max(1, nlk_page - 2)
        end_page   = min(nlk_total_pages, nlk_page + 2)
        opts       = list(range(start_page, end_page + 1))
        st.markdown('<div data-testid="nlk_pager">', unsafe_allow_html=True)
        sel = st.radio("NLK 페이지", opts, index=opts.index(nlk_page),
                       horizontal=True, label_visibility="collapsed",
                       key=f"nlk_radio_{active_kw}")
        st.markdown('</div>', unsafe_allow_html=True)
        if sel != nlk_page:
            st.session_state.nlk_page = int(sel)
            st.rerun()

# ===== 오른쪽: 알라딘 =====
with col_right:
    st.subheader("알라딘")
    st.caption(f"총 {aladin_total}건 · {aladin_page}/{aladin_total_pages}페이지")
    if aladin_docs:
        for d in aladin_docs:
            with st.container(border=True):
                title = d.get("TITLE", "제목 없음")
                link  = d.get("LINK", "")
                st.markdown(f"**[{title}]({link})**" if link else f"**{title}**")
                st.caption(
                    f"저자: {d.get('AUTHOR','정보 없음')} · "
                    f"출판사: {d.get('PUBLISHER','정보 없음')} · "
                    f"출간일: {d.get('PUBDATE','정보 없음')}"
                )
                cover = d.get("COVER", "")
                if cover:
                    st.image(cover, use_container_width=True)
    else:
        st.info("검색 결과가 없습니다.")

    if aladin_total_pages > 1:
        start_page = max(1, aladin_page - 2)
        end_page   = min(aladin_total_pages, aladin_page + 2)
        opts       = list(range(start_page, end_page + 1))
        st.markdown('<div data-testid="aladin_pager">', unsafe_allow_html=True)
        sel = st.radio("ALADIN 페이지", opts, index=opts.index(aladin_page),
                       horizontal=True, label_visibility="collapsed",
                       key=f"aladin_radio_{active_kw}")
        st.markdown('</div>', unsafe_allow_html=True)
        if sel != aladin_page:
            st.session_state.aladin_page = int(sel)
            st.rerun()