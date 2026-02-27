# NAPI (도서 통합 검색)

전남연구원 로컬 도서 데이터와 외부 Open API를 함께 조회하는 Streamlit 앱입니다.

- 작성자: 한국전자통신연구원 배성진(sjbae7@etri.re.kr)
- 최종 코드 업데이트시간: 2026-02-27 08:20

## 주요 기능

- 전남연구원 로컬 JSON 검색
- 국립중앙도서관 OpenAPI 검색
- 알라딘 API 검색
- RISS API 검색
- 4열 결과 비교 화면 및 페이지네이션

## 프로젝트 구조

- `app.py`: 메인 Streamlit 앱
- `static/전남연구원.json`: 로컬 도서 데이터
- `.streamlit/config.toml`: Streamlit 서버 설정
- `requirements.txt`: Python 의존성

## 실행 방법 (로컬)

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Secrets 설정

앱 실행 전 Streamlit Secrets에 아래 값을 등록해야 합니다.

```toml
ALADIN_TTB_KEY = "..."
NLK_OPENAPI_KEY = "..."
RISS_API_KEY = "..."
```

- `NLK_OPENAPI_KEY`가 우선 사용됩니다.
- `NLK_CERT_KEY`는 하위호환용 대체 키입니다.
- `RISS_PROXY_BASE`는 선택값이며, 없으면 RISS 기본 엔드포인트를 사용합니다.

## 배포 메모

- Streamlit Community Cloud 사용 시 `App Settings > Secrets`에 키를 등록하세요.
- API 키를 코드/저장소에 직접 넣지 마세요.

