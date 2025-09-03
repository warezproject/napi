import json
from pathlib import Path
from urllib.parse import quote_plus
import re
import xml.etree.ElementTree as ET
import requests
import streamlit as st
from concurrent.futures import ThreadPoolExecutor


# -----------------------------
# 기본 설정
# -----------------------------
st.set_page_config(page_title="국가정보정책협의회 분과위원회 TEST", layout="wide")
st.title("국가정보정책협의회 TEST")
st.caption("전남연구원 로컬 데이터 + 국립중앙도서관 API + 알라딘 API + RISS 단행본 API")
st.caption("※RISS는 API 정책상 최대 100건까지만 표출됩니다.")
st.caption("최종 수정시간: 2025-09-03 10:40")

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
            
div[data-testid="riss_pager"] .stRadio > div { gap: 4px !important; }
div[data-testid="riss_pager"] label { padding: 2px 6px !important; border: 1px solid #ddd; border-radius: 6px; }
div[data-testid="riss_pager"] input:checked + div { font-weight: 700; }
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
if "riss_page" not in st.session_state:
    st.session_state.riss_page = 1
if "nlk_prefetched_pages" not in st.session_state:
    st.session_state.nlk_prefetched_pages = 10  # 최초 1~10
if "aladin_prefetched_pages" not in st.session_state:
    st.session_state.aladin_prefetched_pages = 10

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
    st.session_state.aladin_page = 1
    st.session_state.riss_page = 1
    st.session_state.nlk_prefetched_pages = 10          # ✅ 리셋
    st.session_state.aladin_prefetched_pages = 10       # ✅ 리셋
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
# 국립중앙도서관 API 호출
# -----------------------------
def call_nlk_api(keyword: str, page_num: int = 1, page_size: int = 10):
    """
    국립중앙도서관 OpenAPI (XML) 호출 → <detail_link> 포함된 결과 반환
    """
    if not keyword:
        return [], 0

    api_key = st.secrets.get("NLK_OPENAPI_KEY") or st.secrets.get("NLK_CERT_KEY")
    if not api_key:
        st.error("Secrets에 NLK_OPENAPI_KEY (또는 NLK_CERT_KEY)가 없습니다.")
        return [], 0

    url = "https://www.nl.go.kr/NL/search/openApi/search.do"
    params = {
        "key": api_key,
        "apiType": "xml",
        "srchTarget": "total",
        "kwd": keyword,
        "pageNum": page_num,
        "pageSize": page_size,
        "sort": "",
        "category": "도서"
    }
    headers = {"User-Agent": "Mozilla/5.0 (Streamlit XML Client)"}

    try:
        r = requests.get(url, params=params, headers=headers, timeout=12)
        r.raise_for_status()

        root = ET.fromstring(r.text)

        # 전체 건수
        total_str = root.findtext(".//paramData/total") or "0"
        total = int(total_str) if total_str.isdigit() else 0

        docs = []
        for item in root.findall(".//result/item"):
            title = (item.findtext("title_info") or "").strip() or "제목 없음"
            author = (item.findtext("author_info") or "").strip() or "정보 없음"
            publisher = (item.findtext("pub_info") or "").strip() or "정보 없음"
            year = (item.findtext("pub_year_info") or "").strip() or "정보 없음"
            isbn = (item.findtext("isbn") or "").strip()
            detail_link = (item.findtext("detail_link") or "").strip()
            if detail_link.startswith("/"):
                detail_link = f"https://www.nl.go.kr{detail_link}"

            docs.append({
                "TITLE": title,
                "AUTHOR": author,
                "PUBLISHER": publisher,
                "PUBLISH_YEAR": year,
                "ISBN": isbn,
                "DETAIL_LINK": detail_link
            })
        return docs, total

    except Exception as e:
        st.warning(f"NLK OpenAPI 호출 오류: {e}")
        return [], 0
# -----------------------------
# RISS API 호출
# -----------------------------
def call_riss_api(keyword: str, rowcount):
    """
    RISS Open API 호출
    - 엔드포인트(기본): http://www.riss.kr/openApi
    - 응답: <record><head>...<totalcount>...</totalcount>...<metadata>...</metadata>...</record>
    - 반환: (docs, totalcount)
    - 페이지 파라미터가 공식 제공되지 않아 보이므로(제공 시 문서에 맞춰 확장),
      한 번 호출로 받아온 결과를 클라이언트 사이드에서 페이지네이션합니다.
    """
    if not keyword:
        return [], 0

    api_key = st.secrets.get("RISS_API_KEY")
    if not api_key:
        st.error("Secrets에 RISS_API_KEY가 없습니다.")
        return [], 0
    
    base = st.secrets.get("RISS_PROXY_BASE", "").rstrip("/")
    if base:
        # 프록시(HTTPS) 경유: ?key=&version=1.0&type=U&keyword=...
        url = f"{base}/"
        params = {"key": api_key, "version": "1.0", "type": "U", "rowcount": min(max(int(rowcount), 1), 100), "stype": "ab", "keyword": keyword}
    else:
        # 직접 호출(HTTP). Streamlit Cloud에서 HTTP가 막히면 프록시 사용을 권장
        url = "http://www.riss.kr/openApi"
        params = {"key": api_key, "version": "1.0", "type": "U", "rowcount": min(max(int(rowcount), 1), 100), "stype": "ab", "keyword": keyword}

    headers = {"User-Agent": "Mozilla/5.0 (Streamlit RISS Client)"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=12)
        r.raise_for_status()
        root = ET.fromstring(r.text)

        # totalcount
        total_str = (root.findtext(".//totalcount") or "0").strip()
        try:
            total = int(total_str)
        except:
            total = 0

        docs = []
        for md in root.findall(".//metadata"):
            title   = (md.findtext("riss.title") or "").strip() or "제목 없음"
            author  = (md.findtext("riss.author") or "").strip() or "정보 없음"
            pub     = (md.findtext("riss.publisher") or "").strip() or "정보 없음"
            pdate   = (md.findtext("riss.pubdate") or "").strip()
            mtype   = (md.findtext("riss.mtype") or "").strip()
            url     = (md.findtext("url") or "").strip()

            # holdings가 여러 번 나올 수 있음 → '; '로 합치기
            holdings_nodes = md.findall("riss.holdings")
            holdings = "; ".join([(n.text or "").strip() for n in holdings_nodes if (n is not None and n.text)])

            docs.append({
                "TITLE": title,
                "AUTHOR": author,
                "PUBLISHER": pub,
                "PUBDATE": pdate,
                "MTYPE": mtype,
                "HOLDINGS": holdings,
                "URL": url,
            })

        # RISS는 페이지 파라미터가 문서에 없으므로, 여기서는 한 번 받아온 리스트만 반환
        # (필요시 프록시에서 페이지 기능을 보강 가능)
        return docs, total

    except Exception as e:
        st.warning(f"RISS API 호출/파싱 오류: {e}")
        return [], 0

# -----------------------------
# 공통 헬퍼
# -----------------------------
def make_page_window(current: int, total_pages: int, window: int = 10):
    """
    총 페이지 중에서 현재 페이지를 중심으로 window(기본 10) 크기의 페이지 목록을 만든다.
    - total_pages <= window 면 1..total_pages
    - 처음엔 1..10, 끝 근처에선 total_pages-9..total_pages
    """
    if total_pages <= window:
        return list(range(1, total_pages + 1))
    # 기본: current를 가운데에 두려고 시도
    half = window // 2
    start = max(1, current - half)
    end = start + window - 1
    # 끝을 넘으면 뒤에서 당겨오기
    if end > total_pages:
        end = total_pages
        start = end - window + 1
    return list(range(start, end + 1))

# -----------------------------
# 미리가져오기(prefetch)
# -----------------------------
PREFETCH_PAGES = 10
@st.cache_data(show_spinner=True)
def prefetch_nlk(keyword: str, page_size: int = PAGE_SIZE, pages: int = PREFETCH_PAGES):
    """NLK: 1~pages 페이지까지 미리 가져와서 리스트로 합치기"""
    all_docs, total = [], 0
    if not keyword:
        return all_docs, total
    for p in range(1, pages + 1):
        docs, t = call_nlk_api(keyword, page_num=p, page_size=page_size)
        if total == 0:
            total = t
        if not docs:
            break
        all_docs.extend(docs)
        if len(docs) < page_size:
            break
    # 최대 pages*page_size까지만 캐시(과도 확장 방지)
    return all_docs[:pages * page_size], total

@st.cache_data(show_spinner=True)
def prefetch_aladin(keyword: str, page_size: int = PAGE_SIZE, pages: int = PREFETCH_PAGES):
    """알라딘: 1~pages 페이지까지 미리 가져와서 리스트로 합치기"""
    all_docs, total = [], 0
    if not keyword:
        return all_docs, total
    for p in range(1, pages + 1):
        docs, t = call_aladin_api(keyword, page_num=p, page_size=page_size, query_type="Title")
        if total == 0:
            total = t
        if not docs:
            break
        all_docs.extend(docs)
        if len(docs) < page_size:
            break
    return all_docs[:pages * page_size], total

@st.cache_data(show_spinner=True)
def prefetch_riss(keyword: str, rowcount: int = 100):
    """
    RISS: rowcount=100으로 한 번에 받아오면 끝.
    (이미 최대 100개라 추가 호출 불필요)
    """
    docs, total = call_riss_api(keyword, rowcount=rowcount)  # 당신의 call_riss_api 최신 시그니처 사용
    return docs, total

# JNDI는 로컬 JSON이므로 별도 네트워크 호출 없음 -> 필터 후 슬라이스만

# ===================== BEGIN: 4열 렌더링 (왼:JNDI · 중1:NLK · 중2:알라딘 · 오른:RISS) =====================
PAGE_SIZE = 10
active_kw = st.session_state.query

# ===== 전남연구원 (로컬) =====
jndi_all, _meta = load_jndi_json_best_effort()
jndi_hits = search_jndi(jndi_all, active_kw)
jndi_total = len(jndi_hits)
jndi_total_pages = max(1, min(PREFETCH_PAGES, (jndi_total + PAGE_SIZE - 1) // PAGE_SIZE))  # 최대 10페이지까지만 노출
jndi_page = st.session_state.jndi_page
j_start = (jndi_page - 1) * PAGE_SIZE
j_end   = j_start + PAGE_SIZE
jndi_page_data = jndi_hits[j_start:j_end]

# 현재 선택 페이지
nlk_page    = st.session_state.nlk_page
aladin_page = st.session_state.aladin_page
riss_page   = st.session_state.riss_page

# 먼저 1페이지만 가볍게 가져가 total 계산? → 우리는 prefetch_nlk/aladin이 total도 반환하므로,
# 바로 prefetch를 돌리되, "요청 pages"를 동적으로 설정.

# 1) 먼저 현재 저장된 프리패치 범위 사용
req_nlk_pages    = st.session_state.nlk_prefetched_pages
req_aladin_pages = st.session_state.aladin_prefetched_pages

# 2) 병렬 prefetch (요청한 pages까지)
with st.spinner("검색중…"):
    with ThreadPoolExecutor(max_workers=3) as pool:
        fut_nlk    = pool.submit(prefetch_nlk,    active_kw, PAGE_SIZE, req_nlk_pages)
        fut_aladin = pool.submit(prefetch_aladin, active_kw, PAGE_SIZE, req_aladin_pages)
        fut_riss   = pool.submit(prefetch_riss,   active_kw, 100)

        nlk_docs_prefetched,    nlk_total    = fut_nlk.result()
        aladin_docs_prefetched, aladin_total = fut_aladin.result()
        riss_docs_prefetched,   riss_total   = fut_riss.result()

# API total 기반 전체 페이지(표시용) 계산 — ✅ 여기서는 "캡을 두지 말 것"
nlk_total_pages_all    = max(1, (nlk_total    + PAGE_SIZE - 1) // PAGE_SIZE)
aladin_total_pages_all = max(1, (aladin_total + PAGE_SIZE - 1) // PAGE_SIZE)

# 사용자가 11 이상 선택했다면, 프리패치 범위를 다음 블록(예: 20)까지 확장
def _next_block_end(p):   # 10, 20, 30...
    return ((p - 1) // 10 + 1) * 10

need_nlk_pages    = _next_block_end(nlk_page)
need_aladin_pages = _next_block_end(aladin_page)

# 전체 페이지를 넘지 않도록 클램프(표시만 큰 경우에도 불필요한 fetch 방지)
need_nlk_pages    = min(need_nlk_pages,    nlk_total_pages_all)
need_aladin_pages = min(need_aladin_pages, aladin_total_pages_all)

# 필요시 즉시 확장 prefetch (재호출해도 cache_data가 있어 이미 내려받은 페이지는 빠르게 반환)
if need_nlk_pages > req_nlk_pages:
    nlk_docs_prefetched, nlk_total = prefetch_nlk(active_kw, PAGE_SIZE, need_nlk_pages)
    st.session_state.nlk_prefetched_pages = need_nlk_pages

if need_aladin_pages > req_aladin_pages:
    aladin_docs_prefetched, aladin_total = prefetch_aladin(active_kw, PAGE_SIZE, need_aladin_pages)
    st.session_state.aladin_prefetched_pages = need_aladin_pages

# 최종 카운트/표시 페이지 계산 (표시는 전체 페이지, 데이터 슬라이스는 현재 프리패치 범위 내에서)
nlk_prefetched_count    = len(nlk_docs_prefetched)       # ≤ need_nlk_pages*PAGE_SIZE
aladin_prefetched_count = len(aladin_docs_prefetched)
riss_count              = len(riss_docs_prefetched)      # ≤ 100

# "표시용 전체 페이지"는 API total 기준으로,
# "실제 슬라이스"는 prefetched 문서에서 자릅니다.
n_start = (nlk_page - 1) * PAGE_SIZE
n_end   = n_start + PAGE_SIZE
nlk_page_data = nlk_docs_prefetched[n_start:n_end]

a_start = (aladin_page - 1) * PAGE_SIZE
a_end   = a_start + PAGE_SIZE
aladin_page_data = aladin_docs_prefetched[a_start:a_end]

r_start = (riss_page - 1) * PAGE_SIZE
r_end   = r_start + PAGE_SIZE
riss_page_data = riss_docs_prefetched[r_start:r_end]


# 4열 레이아웃
st.write("---")
col_left, col_c1, col_c2, col_right = st.columns([1, 1, 1, 1])

# ----- 전남연구원 -----
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
    if jndi_total_pages > 1:
        opts = make_page_window(jndi_page, jndi_total_pages, window=10)  # ✅ 1~10 기본
        st.markdown('<div data-testid="jndi_pager">', unsafe_allow_html=True)
        sel = st.radio(
            "JNDI 페이지", opts,
            index=opts.index(jndi_page),
            horizontal=True, label_visibility="collapsed",
            key=f"jndi_radio_{active_kw}",
        )
        st.markdown('</div>', unsafe_allow_html=True)
        if sel != jndi_page:
            st.session_state.jndi_page = int(sel)
            st.rerun()


# ----- 국립중앙도서관 -----
with col_c1:
    st.subheader("국립중앙도서관")
    st.caption(f"총 {nlk_total}건 · {nlk_page}/{nlk_total_pages_all}페이지")
    if nlk_page_data:
        for d in nlk_page_data:
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
    if nlk_total_pages_all > 1:
        opts = make_page_window(nlk_page, nlk_total_pages_all, window=10)    # ✅ 1~10 기본
        st.markdown('<div data-testid="nlk_pager">', unsafe_allow_html=True)
        sel = st.radio(
            "NLK 페이지", opts,
            index=opts.index(nlk_page),
            horizontal=True, label_visibility="collapsed",
            key=f"nlk_radio_{active_kw}",
        )
        st.markdown('</div>', unsafe_allow_html=True)
        if sel != nlk_page:
            st.session_state.nlk_page = int(sel)
            st.rerun()

# ----- 알라딘 (표지 미표시 버전) -----
with col_c2:
    st.subheader("알라딘")
    st.caption(f"총 {aladin_total}건 · {aladin_page}/{aladin_total_pages_all}페이지")
    if aladin_page_data:
        for d in aladin_page_data:
            with st.container(border=True):
                title = d.get("TITLE", "제목 없음")
                link  = d.get("LINK", "")
                st.markdown(f"**[{title}]({link})**" if link else f"**{title}**")
                st.caption(
                    f"저자: {d.get('AUTHOR','정보 없음')} · "
                    f"출판사: {d.get('PUBLISHER','정보 없음')} · "
                    f"출간일: {d.get('PUBDATE','정보 없음')}"
                )
    else:
        st.info("검색 결과가 없습니다.")
    if aladin_total_pages_all > 1:
        opts = make_page_window(aladin_page, aladin_total_pages_all, window=10)  # ✅ 1~10 기본
        st.markdown('<div data-testid="aladin_pager">', unsafe_allow_html=True)
        sel = st.radio(
            "ALADIN 페이지", opts,
            index=opts.index(aladin_page),
            horizontal=True, label_visibility="collapsed",
            key=f"aladin_radio_{active_kw}",
        )
        st.markdown('</div>', unsafe_allow_html=True)
        if sel != aladin_page:
            st.session_state.aladin_page = int(sel)
            st.rerun()

# ----- RISS -----
with col_right:
    riss_total_pages = max(1, (riss_count + PAGE_SIZE - 1)//PAGE_SIZE) 
    st.subheader("RISS")
    # total은 전체 건수(100 초과 가능), count는 실제 가져온 수(≤100)
    st.caption(f"총 {riss_total}건 (표시 {riss_count}건) · {riss_page}/{riss_total_pages}페이지")
    if riss_page_data:
        for d in riss_page_data:
            with st.container(border=True):
                title = d.get("TITLE", "제목 없음")
                url   = d.get("URL", "")
                st.markdown(f"**[{title}]({url})**" if url else f"**{title}**")
                st.caption(
                    f"저자: {d.get('AUTHOR','정보 없음')} · "
                    f"출판사: {d.get('PUBLISHER','정보 없음')} · "
                    f"발행년도: {d.get('PUBDATE','정보 없음')} · "
                    f"자료유형: {d.get('MTYPE','정보 없음')}"
                )
                holdings = d.get("HOLDINGS", "")
                if holdings:
                    st.code(f"소장처: {holdings}", language="text")
    else:
        st.info("검색 결과가 없습니다.")

    # 하단 라디오 페이지네이션 (가로·촘촘)
    if riss_total_pages > 1:
        opts = make_page_window(riss_page, riss_total_pages, window=10)  # ✅ 1~10 기본
        st.markdown('<div data-testid="riss_pager">', unsafe_allow_html=True)
        sel = st.radio(
            "RISS 페이지", opts,
            index=opts.index(riss_page),
            horizontal=True, label_visibility="collapsed",
            key=f"riss_radio_{active_kw}",
        )
        st.markdown('</div>', unsafe_allow_html=True)
        if sel != riss_page:
            st.session_state.riss_page = int(sel)
            st.rerun()
# ===================== END: 4열 렌더링 =====================
