import json
from pathlib import Path
from urllib.parse import quote_plus
import requests
import streamlit as st

# -----------------------------
# 기본 설정
# -----------------------------
st.set_page_config(page_title="국가정보정책협의회 TEST", layout="wide")

st.title("국가정보정책협의회 TEST")
st.caption("전남연구원 로컬 데이터 + 국립중앙도서관 Open API (상세페이지 직링크)")

# -----------------------------
# 입력 UI
# -----------------------------
with st.form("search_form", clear_on_submit=False):
    kw = st.text_input("도서 제목을 입력하세요", value="", placeholder="예: 딥러닝, 머신러닝, 인공지능 …")
    submitted = st.form_submit_button("검색")

# -----------------------------
# 헬퍼 함수
# -----------------------------
@st.cache_data(show_spinner=False)
def load_jndi_json(json_path: Path):
    if not json_path.exists():
        return [], {"exists": False, "count": 0, "path": str(json_path)}
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        return data, {"exists": True, "count": len(data), "path": str(json_path)}
    except Exception as e:
        st.warning(f"전남연구원 JSON 읽기 오류: {e}")
        return [], {"exists": True, "count": 0, "path": str(json_path)}

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

# ---- NLK Open API 정규화 도우미 (가이드 기준) ----
def _detail_link_from(rec: dict) -> str:
    """1) detail_link 2) isbn 3) control_no 순으로 상세 URL 생성."""
    detail = (rec.get("detail_link") or rec.get("DETAIL_LINK") or "").strip()
    if detail:
        # 일부 응답은 상대경로일 수 있으므로 보정
        if detail.startswith("/"):
            return f"https://www.nl.go.kr{detail}"
        return detail

    # 보강 생성
    isbn = (rec.get("isbn") or rec.get("ISBN") or "").strip()
    if isbn:
        return f"https://www.nl.go.kr/search/SearchDetail.do?isbn={quote_plus(isbn)}"

    control = (
        rec.get("control_no") or rec.get("CONTROL_NO") or
        rec.get("CONTROLNO") or rec.get("cn") or rec.get("CN") or ""
    )
    if control:
        return f"https://www.nl.go.kr/search/SearchDetail.do?cn={quote_plus(str(control))}"

    # 최후 fallback: 제목으로 통합검색
    title = (rec.get("title_info") or rec.get("TITLE") or rec.get("title") or "").strip()
    if title:
        return f"https://www.nl.go.kr/search/searchResult.jsp?category=total&kwd={quote_plus(title)}"
    return "https://www.nl.go.kr"

def _normalize_nlk_record(rec: dict) -> dict:
    """가이드의 응답 필드를 앱 내부 공통키로 정규화."""
    title = rec.get("title_info") or rec.get("TITLE") or rec.get("title") or "제목 없음"
    author = rec.get("author_info") or rec.get("AUTHOR") or rec.get("author") or "정보 없음"
    publisher = rec.get("pub_info") or rec.get("PUBLISHER") or rec.get("publisher") or "정보 없음"
    pub_year = rec.get("pub_year_info") or rec.get("PUBLISH_YEAR") or rec.get("year") or "정보 없음"
    isbn = (rec.get("isbn") or rec.get("ISBN") or "").strip()
    link = _detail_link_from(rec)
    return {
        "TITLE": title,
        "AUTHOR": author,
        "PUBLISHER": publisher,
        "PUBLISH_YEAR": pub_year,
        "ISBN": isbn,
        "DETAIL_LINK": link,
        # 참고용으로 원본 제어번호도 같이 보관
        "CONTROL_NO": rec.get("control_no") or rec.get("CONTROL_NO") or rec.get("cn") or rec.get("CN") or ""
    }

def _extract_openapi_list(data: dict):
    """
    Open API 응답에서 레코드 리스트를 최대로 유연하게 추출.
    가이드에서는 필드 목록만 제시되므로 다양한 가능성 대응.
    """
    if not isinstance(data, dict):
        return []
    # 흔한 케이스들 우선 시도
    for key in ("result", "items", "docs", "list", "seoji"):
        v = data.get(key)
        if isinstance(v, list):
            return v
    # 일부 구현은 바로 리스트를 줄 수도 있음
    return data.get("data", []) if isinstance(data.get("data"), list) else []

def call_nlk_api(keyword: str):
    """
    국립중앙도서관 Open API (search.do) 호출.
    - 엔드포인트: https://www.nl.go.kr/NL/search/openApi/search.do
    - 필수 파라미터: key, pageNum, pageSize
    - 선택: srchTarget=total, kwd=검색어, apiType=json
    """
    if not keyword:
        return []

    # 1) 프록시(Cloudflare Worker 등)를 쓰는 경우 (선택)
    proxy_base = st.secrets.get("NLK_PROXY_BASE", "").rstrip("/")
    if proxy_base:
        try:
            # 프록시가 Open API를 대신 호출해 준다고 가정 (title, page_no, page_size 전달)
            r = requests.get(
                f"{proxy_base}/",
                params={"title": keyword, "page_no": 1, "page_size": 10},
                timeout=12,
                headers={"User-Agent": "Mozilla/5.0 (Streamlit App via Proxy)"}
            )
            # 프록시가 Open API 원본 구조를 되돌려줄 수도 있고, docs로 감싸줄 수도 있으므로 모두 허용
            raw = r.json()
            if isinstance(raw, dict):
                rows = _extract_openapi_list(raw) or raw.get("docs") or []
            elif isinstance(raw, list):
                rows = raw
            else:
                rows = []
            return [_normalize_nlk_record(rec) for rec in rows]
        except Exception as e:
            st.info(f"프록시 실패: {e}")

    # 2) 직접 호출 (가이드 준수)
    #    - secrets에서 키를 NLK_OPENAPI_KEY 우선, 없으면 NLK_CERT_KEY 재사용(이전 호환)
    api_key = st.secrets.get("NLK_OPENAPI_KEY") or st.secrets.get("NLK_CERT_KEY")
    if not api_key:
        st.error("Secrets에 NLK_OPENAPI_KEY (또는 NLK_CERT_KEY)가 없습니다.")
        return []

    url = "https://www.nl.go.kr/NL/search/openApi/search.do"
    params = {
        "key": api_key,            # 발급키 (필수)
        "apiType": "json",         # JSON 응답
        "srchTarget": "total",     # 전체 검색
        "kwd": keyword,            # 검색어
        "pageNum": 1,              # 현재 페이지 (필수)
        "pageSize": 10             # 페이지 당 건수 (필수)
        # 필요 시 systemType/govYn/category 등 추가 가능
    }
    headers = {"User-Agent": "Mozilla/5.0 (Streamlit App)"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=12)
        data = r.json()
        rows = _extract_openapi_list(data)
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
# ⚠️ 현재 파일명이 'static/전남연구원.json'로 되어 있습니다.
#    실제 저장소의 파일명과 반드시 일치시켜 주세요.
jndi_all, jndi_meta = load_jndi_json(Path("static/전남연구원.json"))

# -----------------------------
# 검색 실행
# -----------------------------
if submitted:
    # 전남연구원 검색
    jndi_hits = search_jndi(jndi_all, kw)

    # NLK Open API 검색 (상세 링크 포함)
    nlk_docs = call_nlk_api(kw)

    # -----------------------------
    # 결과 표시
    # -----------------------------
    st.write("---")
    cols = st.columns([1, 1])

    # 전남연구원
    with cols[0]:
        st.subheader("전남연구원 검색 결과")
        st.caption(f"로컬 데이터: 존재={jndi_meta['exists']} · 경로={jndi_meta['path']} · 총 {jndi_meta['count']}건")
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

    # (선택) 디버그: 첫 결과의 원본 키 확인
    # with st.expander("NLK 첫 건 raw JSON"):
    #     if nlk_docs:
    #         st.json(nlk_docs[0])

else:
    st.info("상단 입력창에 검색어를 입력하고 **검색** 버튼을 눌러주세요.")
