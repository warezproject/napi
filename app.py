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
st.caption("전남연구원 로컬 데이터 + 국립중앙도서관 API 서버사이드 검색 (상세페이지 직링크)")

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

def _build_detail_link(rec: dict) -> str:
    """
    NLK 상세페이지 직링크를 만든다.
    우선순위: ISBN -> CN/CONTROL_NO(서지번호 계열) -> (최후) 제목 검색
    """
    # 어떤 키로 오는지 케이스가 달라 다양한 후보를 본다
    isbn = (rec.get("ISBN") or rec.get("Isbn") or rec.get("isbn") or "").strip()
    cn = (
        rec.get("CN")
        or rec.get("ControlNo")
        or rec.get("CONTROL_NO")
        or rec.get("CONTROLNO")
        or rec.get("DOCID")
        or rec.get("DOC_ID")
        or rec.get("BIB_ID")
        or ""
    )
    title = (rec.get("TITLE") or rec.get("Title") or rec.get("title") or "").strip()

    if isbn:
        return f"https://www.nl.go.kr/search/SearchDetail.do?isbn={quote_plus(isbn)}"
    if cn:
        return f"https://www.nl.go.kr/search/SearchDetail.do?cn={quote_plus(str(cn))}"
    # 최후: 통합검색 페이지로 폴백
    if title:
        return f"https://www.nl.go.kr/search/searchResult.jsp?category=total&kwd={quote_plus(title)}"
    return "https://www.nl.go.kr"

def _normalize_docs(docs):
    """
    docs(list of dict)를 받아 각 아이템에 DETAIL_LINK를 주입해 반환.
    """
    out = []
    for d in docs or []:
        try:
            d = dict(d)  # 방어적 복사
        except Exception:
            continue
        d["DETAIL_LINK"] = _build_detail_link(d)
        out.append(d)
    return out

def call_nlk_api(keyword: str):
    """Cloudflare Worker 프록시만 사용(DETAIL_LINK는 Worker가 주입)"""
    if not keyword:
        return []

    proxy_base = st.secrets.get("NLK_PROXY_BASE", "").rstrip("/")
    if not proxy_base:
        st.error("Secrets에 NLK_PROXY_BASE가 없습니다. Cloudflare Worker 주소를 NLK_PROXY_BASE로 추가하세요.")
        return []

    try:
        r = requests.get(
            f"{proxy_base}/",
            params={"title": keyword, "page_no": 1, "page_size": 10},
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (Streamlit App via Proxy)"}
        )
        data = r.json()
        docs = data.get("docs", []) if isinstance(data, dict) else data
        return docs if isinstance(docs, list) else []
    except Exception as e:
        st.error(f"프록시 호출 오류: {e}")
        return []


def aladin_cover_from_isbn(isbn: str):
    """간단 커버 URL 추정(성공 보장 X) - 없으면 빈 문자열"""
    if not isbn:
        return ""
    return f"https://image.aladin.co.kr/product/{isbn[-3:]}/{isbn[-5:]}cover.jpg"

# -----------------------------
# 데이터 로드 (실제 파일명에 맞춤)
# -----------------------------
# ※ 이전에 'static/전남연구원.json'을 쓰셨다면 파일명을 통일하세요.
jndi_all, jndi_meta = load_jndi_json(Path("static/전남연구원.json"))

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
                    # 🔴 여기! DETAIL_LINK 우선 사용
                    link = d.get("DETAIL_LINK")
                    if not link:  # 혹시 Worker가 못 넣어줬을 때만 최후 fallback
                        isbn = (d.get("ISBN") or "").strip()
                        cn = (d.get("CN") or d.get("CONTROL_NO") or d.get("CONTROLNO") or "")
                        if isbn:
                            link = f"https://www.nl.go.kr/search/SearchDetail.do?isbn={quote_plus(isbn)}"
                        elif cn:
                            link = f"https://www.nl.go.kr/search/SearchDetail.do?cn={quote_plus(str(cn))}"
                        else:
                            link = f"https://www.nl.go.kr/search/searchResult.jsp?category=total&kwd={quote_plus(title)}"

                    st.markdown(f"**[{title}]({link})**")
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

