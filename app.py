import streamlit as st
import requests, json
from pathlib import Path

st.set_page_config(page_title="국가정보정책협의회 TEST", layout="wide")

st.title("국가정보정책협의회 TEST")

keyword = st.text_input("도서 제목을 입력하세요...")
if st.button("검색"):
    # 1) 전남연구원 로컬 JSON에서 검색
    jndi = json.loads(Path("static/전남연구원.json").read_text(encoding="utf-8"))
    matched = [b for b in jndi if b.get("서명") and keyword in b["서명"]]

    st.subheader("전남연구원 검색 결과")
    if matched:
        for book in matched:
            with st.container(border=True):
                st.markdown(f"**{book.get('서명','')}**")
                st.caption(f"저자: {book.get('저자','정보 없음')} / 발행자: {book.get('발행자','정보 없음')} / 발행년도: {book.get('발행년도','정보 없음')}")
                st.code(f"등록번호: {book.get('등록번호','')}")
    else:
        st.info("검색 결과가 없습니다.")

    # 2) 국립중앙도서관 API (서버사이드 호출)
    CERT_KEY = st.secrets["NLK_CERT_KEY"]
    url = "https://www.nl.go.kr/seoji/SearchApi.do"
    params = {
        "cert_key": CERT_KEY,
        "result_style": "json",
        "page_no": 1,
        "page_size": 10,
        "title": keyword or ""
    }
    r = requests.get(url, params=params, timeout=10)
    data = r.json()

    st.subheader("국립중앙도서관 검색 결과")
    docs = data.get("docs", [])
    if docs:
        for d in docs:
            isbn = d.get("ISBN","")
            link = f"https://www.nl.go.kr/search/searchResult.jsp?category=total&kwd={requests.utils.quote(d.get('TITLE',''))}"
            with st.container(border=True):
                st.markdown(f"**[{d.get('TITLE','제목 없음')}]({link})**")
                st.caption(f"저자: {d.get('AUTHOR','정보 없음')} / 출판사: {d.get('PUBLISHER','정보 없음')} / 발행년도: {d.get('PUBLISH_YEAR','정보 없음')}")
                st.code(f"ISBN: {isbn}")
    else:
        st.info("검색 결과가 없습니다.")
