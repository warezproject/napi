import json
from pathlib import Path
import requests
import streamlit as st

# -----------------------------
# 기본 설정
# -----------------------------
st.set_page_config(page_title="국가정보정책협의회 TEST", layout="wide")

st.title("국가정보정책협의회 TEST")
st.caption("전남연구원 로컬 데이터 + 국립중앙도서관 API 서버사이드 검색")

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
        return [], {"exists": False, "count": 0}
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        return data, {"exists": True, "count": len(data)}
    except Exception as e:
        st.warning(f"전남연구원 JSON 읽기 오류: {e}")
        return [], {"exists": True, "count": 0}

def search_jndi(records, keyword: str):
    if not keyword:
        return []
    key_candidates = ("서명", "서명 ", "Title", "title")
    low_kw = keyword.casefold()
    matched = []
    for rec in records:
        for k in key_candidates:
            if k in rec and isinstance(rec[k], str):
                if low_kw in rec[k].casefold():
                    matched.append(rec)
                    break
    return matched

def call_nlk_api_simple(keyword: str):
    """
    이전에 성공했던 방식 그대로: 단순 GET + r.json()
    - raise_for_status 사용 안 함
    - User-Agent 헤더만 추가
    """
    if not keyword:
        return []
    try:
        cert_key = st.secrets["NLK_CERT_KEY"]
    except KeyError:
        st.error("Secrets에 NLK_CERT_KEY가 없습니다. Streamlit Cloud 앱 Settings → Secrets에 NLK_CERT_KEY를 추가하세요.")
        return []

    url = "https://www.nl.go.kr/seoji/SearchApi.do"
    params = {
        "cert_key": cert_key,
        "result_style": "json",
        "page_no": 1,
        "page_size": 10,
        "title": keyword or ""
    }
    headers = {"User-Agent": "Mozilla/5.0 (Streamlit App)"}

    try:
        # '예전에 문제 없던' 스타일 유지: timeout=10, raise_for_status() 호출 안 함
        r = requests.get(url, params=params, headers=headers, timeout=10)
        try:
            data = r.json()
        except Exception:
            return []
        return data.get("docs", []) or []
    except Exception as e:
        # 네트워크 타임아웃/연결 문제는 여기로 들어옴
        st.warning(f"국립중앙도서관 API 호출 오류: {e}")
        return []

def aladin_cover_from_isbn(isbn: str):
    """간단 커버 URL 추정(성공 보장 X) - 없으면 빈 문자열"""
    if not isbn:
        return ""
    # 단순 추정 규칙(실패할 수 있음)
    return f"https://image.aladin.co.kr/product/{isbn[-3:]}/{isbn[-5:]}cover.jpg"

# -----------------------------
# 데이터 로드 (실제 파일명에 맞춤)
# -----------------------------
jndi_all, jndi_meta = load_jndi_json(Path("static/전남연구원.json"))

# -----------------------------
# 검색 실행
# -----------------------------
if submitted:
    # 전남연구원 검색
    jndi_hits = search_jndi(jndi_all, kw)

    # NLK API 검색 (단순 호출 버전)
    nlk_docs = call_nlk_api_simple(kw)

    # -----------------------------
    # 결과 표시
    # -----------------------------
    st.write("---")
    cols = st.columns([1, 1])

    # 전남연구원
    with cols[0]:
        st.subheader("전남연구원 검색 결과")
        st.caption(f"로컬 데이터: 존재={jndi_meta['exists']} / 총 {jndi_meta['count']}건")
        if jndi_hits:
            for b in jndi_hits:
                with st.container(border=True):
                    st.markdown(f"**{b.get('서명') or b.get('서명 ') or b.get('Title') or ''}**")
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
                    link = f"https://www.nl.go.kr/search/searchResult.jsp?category=total&kwd={requests.utils.quote(title)}"
                    st.markdown(f"**[{title}]({link})**")
                    st.caption(
                        f"저자: {d.get('AUTHOR','정보 없음')} · "
                        f"출판사: {d.get('PUBLISHER','정보 없음')} · "
                        f"발행년도: {d.get('PUBLISH_YEAR','정보 없음')}"
                    )
                    isbn = d.get("ISBN", "")
                    if isbn:
                        st.code(f"ISBN: {isbn}", language="text")
                        # 선택: 표지 이미지 표시(있으면 보임, 없으면 조용히 패스)
                        cover = aladin_cover_from_isbn(isbn)
                        if cover:
                            st.image(cover, use_container_width=True)
        else:
            st.info("검색 결과가 없습니다.")
else:
    # 첫 화면 도움말
    st.info("상단 입력창에 검색어를 입력하고 **검색** 버튼을 눌러주세요.")