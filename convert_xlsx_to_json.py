import pandas as pd

# 파일 경로
xlsx_path = r"C:\Users\USER\Documents\GitHub\napi\전남연구원.xlsx"
json_path = r"C:\Users\USER\Documents\GitHub\napi\전남연구원.json"

# 엑셀 파일 불러오기 (첫 번째 시트 기준)
df = pd.read_excel(xlsx_path, sheet_name=0)

# DataFrame을 JSON으로 변환 (UTF-8, 한글 깨짐 방지)
df.to_json(json_path, orient="records", force_ascii=False, indent=2)

json_path
