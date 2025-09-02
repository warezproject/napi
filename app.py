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
st.caption("전남연구원 로컬 데이터 + 국립중앙도서관 Open API (ISBN 2차 조회로 상세링크 보강)")

# -----------------------------
# 입력 UI
# -----------------------------
with st.form("search_form", clear_on_submit=False):
    kw = st.text_input("도서 제목을 입력하세요", value="", placeholder="예: 딥러닝, LLM, 인공지능 …")
    submitted = st.form_submit_button("검색")

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

def _normalize_nlk_record(rec: dict) -> dict:
    title = _get_first(rec, ("title_info", "TITLE", "title")) or "제목 없음"
    author = _get_first(rec, ("author_info", "AUTHOR", "author")) or "정보 없음"
    publisher = _get_first(rec, ("pub_info", "PUBLISHER", "publisher")) or "정보 없음"
    pub_year = _get_first(rec, ("pub_year_info", "PUBLISH_YEAR", "year")) or "정보 없음"
    isbn = _extract_isbn(rec)
    link = _extract_detail_link(rec)
    control_no = _extract_cn(rec)
    return {
        "TITLE": title,
        "AUTHOR": author,
        "PUBLISHER": publisher,
        "PUBLISH_YEAR": pub_year,
        "ISBN": isbn,
        "DETAIL_LINK": link,
        "CONTROL_NO": control_no,
        "_raw": rec,
    }

def _extract_list_from_any(data):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for k in ("docs", "result", "items", "list", "seoji", "data"):
        v = data.get(k)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            for kk in ("docs", "items", "list", "data"):
                vv = v.get(kk)
                if isinstance(vv, list):
                    return vv
    for v in data.values():
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            for vv in v.values():
                if isinstance(vv, list):
                    return vv
    return []

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
# 검색 실행
# -----------------------------
if submitted:
    # ----- 전남연구원 -----
    jndi_hits = search_jndi(jndi_all, kw)

    # 페이지네이션 (로컬 데이터)
    page_size = 10
    jndi_total = len(jndi_hits)
    jndi_total_pages = (jndi_total + page_size - 1) // page_size
    jndi_page = st.number_input("전남연구원 페이지", 1, max(1, jndi_total_pages), 1, key="jndi_page")

    start = (jndi_page - 1) * page_size
    end = start + page_size
    jndi_page_data = jndi_hits[start:end]

    # ----- 국립중앙도서관 -----
    nlk_page = st.number_input("국립중앙도서관 페이지", 1, 9999, 1, key="nlk_page")
    nlk_docs, nlk_total = call_nlk_api(kw, page_num=nlk_page, page_size=10)
    nlk_total_pages = (nlk_total + page_size - 1) // page_size

    # -----------------------------
    # 결과 표시
    # -----------------------------
    st.write("---")
    cols = st.columns([1, 1])

    # 전남연구원
    with cols[0]:
        st.subheader("전남연구원 검색 결과")
        st.caption(f"총 {jndi_total}건 / 현재 페이지 {jndi_page}/{jndi_total_pages}")
        if jndi_page_data:
            for b in jndi_page_data:
                with st.container(border=True):
                    title = b.get('서명') or b.get('서명 ') or b.get('Title') or b.get('제목') or ''
                    st.markdown(f"**{title}**")
                    st.caption(
                        f"저자: {b.get('저자','정보 없음')} · "
                        f"발행자: {b.get('발행자','정보 없음')} · "
                        f"발행년도: {b.get('발행년도','정보 없음')}"
                    )
        else:
            st.info("검색 결과가 없습니다.")

    # 국립중앙도서관
    with cols[1]:
        st.subheader("국립중앙도서관 검색 결과")
        st.caption(f"총 {nlk_total}건 / 현재 페이지 {nlk_page}/{nlk_total_pages}")
        if nlk_docs:
            for d in nlk_docs:
                with st.container(border=True):
                    title = d.get("TITLE", "제목 없음")
                    link = d.get("DETAIL_LINK") or ""
                    if link:
                        st.markdown(f"**[{title}]({link})**")
                    else:
                        st.markdown(f"**{title}**")
                    st.caption(
                        f"저자: {d.get('AUTHOR','정보 없음')} · "
                        f"출판사: {d.get('PUBLISHER','정보 없음')} · "
                        f"발행년도: {d.get('PUBLISH_YEAR','정보 없음')}"
                    )
        else:
            st.info("검색 결과가 없습니다.")