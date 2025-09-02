import json
from pathlib import Path
from urllib.parse import quote_plus
import re
import requests
import streamlit as st

# -----------------------------
# 기본 설정
# -----------------------------
st.set_page_config(page_title="국가정보정책협의회 TEST", layout="wide")

st.title("국가정보정책협의회 TEST")
st.caption("전남연구원 로컬 데이터 + 국립중앙도서관 API (상세페이지 직링크 강화)")

# -----------------------------
# 입력 UI
# -----------------------------
with st.form("search_form", clear_on_submit=False):
    kw = st.text_input("도서 제목을 입력하세요", value="", placeholder="예: 딥러닝, LLM, 인공지능 …")
    submitted = st.form_submit_button("검색")

# -----------------------------
# 헬퍼 함수
# -----------------------------
@st.cache_data(show_spinner=False)
def load_jndi_json_best_effort():
    """여러 후보 파일명 시도 + 존재/건수 메타 반환"""
    candidates = [
        Path("static/전남연구원_자료.json"),
        Path("static/전남연구원.json"),
        Path("static/jndi.json"),
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

# ---------- NLK 응답 정규화 & 상세 링크 빌더(강화판) ----------
_ISBN_RE = re.compile(r"[0-9Xx\-]{10,17}")

def _get_first(rec: dict, keys: tuple) -> str:
    """정확한 키 목록으로 우선 탐색(대소문자 변형 포함)"""
    if not isinstance(rec, dict):
        return ""
    for k in keys:
        for cand in (k, k.lower(), k.upper(), k.capitalize()):
            v = rec.get(cand)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return ""

def _get_by_substring(rec: dict, substrings: tuple) -> str:
    """키 이름에 특정 문자열이 포함되면 그 값을 채택(가장 먼저 발견되는 값)"""
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
    # 우선 알려진 키들
    isbn = _get_first(rec, ("ISBN", "isbn", "isbn13", "ISBN13", "ea_isbn", "EA_ISBN", "set_isbn", "SET_ISBN"))
    if not isbn:
        # 키 이름에 'isbn'이 들어가면 그 값 사용
        isbn = _get_by_substring(rec, ("isbn",))
    if not isbn:
        return ""
    # 숫자/하이픈/X만 남기고 후보 추출
    m = _ISBN_RE.findall(isbn)
    if not m:
        return ""
    # 13자리 우선, 없으면 10자리
    candidates = [re.sub(r"[^0-9Xx]", "", s) for s in m]
    for c in candidates:
        if len(c) == 13:
            return c
    for c in candidates:
        if len(c) == 10:
            return c
    # 길이가 애매하면 원문 반환
    return candidates[0] if candidates else isbn

def _extract_cn(rec: dict) -> str:
    # 대표 키들
    cn = _get_first(rec, ("CN", "cn", "control_no", "CONTROL_NO", "controlNo", "CONTROLNO", "docid", "DOCID", "doc_id", "DOC_ID", "bib_id", "BIB_ID"))
    if cn:
        return str(cn).strip()
    # 키 이름에 control 또는 cn이 포함되면 사용
    cn = _get_by_substring(rec, ("control", "cn"))
    return str(cn).strip() if cn else ""

def _extract_detail_link(rec: dict) -> str:
    # 1) detail_link / link / url 류 우선
    detail = _get_first(rec, ("detail_link", "DETAIL_LINK", "link", "LINK", "url", "URL"))
    if not detail:
        # 키 이름에 link/url이 들어가면 사용
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
    # 3) 최후 폴백: 제목검색(어쩔 수 없음)
    title = _get_first(rec, ("title_info", "TITLE", "title"))
    if title:
        return f"https://www.nl.go.kr/search/searchResult.jsp?category=total&kwd={quote_plus(title)}"
    return "https://www.nl.go.kr"

def _normalize_nlk_record(rec: dict) -> dict:
    """응답을 앱 공통 스키마로 정규화"""
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
        "_raw": rec,  # (디버그용) 필요 시 st.json으로 확인 가능
    }

def _extract_list_from_any(data: dict):
    """응답 루트에서 list를 최대한 유연하게 추출"""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    # 자주 보이는 케이스
    for k in ("docs", "result", "items", "list", "seoji", "data"):
        v = data.get(k)
        if isinstance(v, list):
            return v
        # 종종 {"result":{"docs":[...]}} 처럼 중첩됨
        if isinstance(v, dict):
            for kk in ("docs", "items", "list", "data"):
                vv = v.get(kk)
                if isinstance(vv, list):
                    return vv
    # 마지막으로 dict의 값 중 첫 리스트를 찾음
    for v in data.values():
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            for vv in v.values():
                if isinstance(vv, list):
                    return vv
    return []

# ---------- NLK 호출 ----------
def call_nlk_api(keyword: str):
    """
    1) Cloudflare Worker 프록시가 있으면 먼저 호출 (DETAIL_LINK 있을 수도/없을 수도)
    2) 없거나 실패하면 Open API 직접 호출 (search.do)
    """
    if not keyword:
        return []

    # 1) 프록시 우선
    proxy_base = st.secrets.get("NLK_PROXY_BASE", "").rstrip("/")
    if proxy_base:
        try:
            r = requests.get(
                f"{proxy_base}/",
                params={"title": keyword, "page_no": 1, "page_size": 10},
                timeout=12,
                headers={"User-Agent": "Mozilla/5.0 (Streamlit App via Proxy)"}
            )
            raw = r.json()
            rows = _extract_list_from_any(raw)
            return [_normalize_nlk_record(rec) for rec in rows]
        except Exception as e:
            st.info(f"프록시 실패: {e}")

    # 2) Open API 직접 호출
    api_key = st.secrets.get("NLK_OPENAPI_KEY") or st.secrets.get("NLK_CERT_KEY")
    if not api_key:
        st.error("Secrets에 NLK_OPENAPI_KEY (또는 NLK_CERT_KEY)가 없습니다.")
        return []

    url = "https://www.nl.go.kr/NL/search/openApi/search.do"
    params = {
        "key": api_key,
        "apiType": "json",
        "srchTarget": "total",
        "kwd": keyword,
        "pageNum": 1,
        "pageSize": 10
    }
    headers = {"User-Agent": "Mozilla/5.0 (Streamlit App)"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=12)
        data = r.json()
        rows = _extract_list_from_any(data)
        return [_normalize_nlk_record(rec) for rec in rows]
    except Exception as e:
        st.warning(f"국립중앙도서관 Open API 호출 오류: {e}")
        return []

def aladin_cover_from_isbn(isbn: str):
    """간단 커버 URL 추정(성공 보장 X) - 없으면 빈 문자열"""
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
    # 전남연구원 검색
    jndi_hits = search_jndi(jndi_all, kw)

    # NLK API 검색 (상세 링크 포함)
    nlk_docs = call_nlk_api(kw)

    # -----------------------------
    # 결과 표시
    # -----------------------------
    st.write("---")
    cols = st.columns([1, 1])

    # 전남연구원
    with cols[0]:
        st.subheader("전남연구원 검색 결과")
        st.caption(f"로컬 데이터: 존재={jndi_meta['exists']} · 경로={jndi_meta.get('path')} · 총 {jndi_meta['count']}건")
        if jndi_hits:
            for b in jndi_hits:
                with st.container(border=True):
                    title = b.get('서명') or b.get('서명 ') or b.get('Title') or b.get('제목') or ''
                    st.markdown(f"**{title}**")
                    st.caption(
                        f"저자: {b.get('저자','정보 없음')} · "
                        f"발행자: {b.get('발행자','정보 없음')} · "
                        f"발행년도: {b.get('발행년도','정보 없음')}"
                    )
                    regno = b.get("등록번호", "")
                    if regno:
                        st.code(f"등록번호: {regno}", language="text")
        else:
            st.info("검색 결과가 없습니다.")

    # 국립중앙도서관
    with cols[1]:
        st.subheader("국립중앙도서관 검색 결과")
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
                    isbn = (d.get("ISBN") or "").strip()
                    if isbn:
                        st.code(f"ISBN: {isbn}", language="text")
                        cover = aladin_cover_from_isbn(isbn)
                        if cover:
                            st.image(cover, use_container_width=True)

        else:
            st.info("검색 결과가 없습니다.")

    # (선택) 디버그: 첫 결과 원본 확인용
    # with st.expander("NLK 첫 건 raw JSON"):
    #     if nlk_docs:
    #         st.json(nlk_docs[0]["_raw"])

else:
    st.info("상단 입력창에 검색어를 입력하고 **검색** 버튼을 눌러주세요.")
