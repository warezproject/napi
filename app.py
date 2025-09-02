# app.py
import streamlit as st
from pathlib import Path

st.set_page_config(page_title="국가정보정책협의회 TEST", layout="wide")

# index.html 읽어서 그대로 iframe으로 표시
html = Path("index.html").read_text(encoding="utf-8")

# st.components.v1.html 로 임베드
import streamlit.components.v1 as components
components.html(html, height=1600, scrolling=True)