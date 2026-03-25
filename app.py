import streamlit as st
from google import genai
from google.genai import types
import json
import os
import re
import time
import difflib
import csv
import io
import gspread
from oauth2client.service_account import ServiceAccountCredentials

import tempfile

import pandas as pd
# # 앱이 실행될 때 한 번만 학생 데이터베이스(DataFrame)를 초기화합니다.
STUDENT_DB_FILE = "students.csv"

def load_student_db():
    if os.path.exists(STUDENT_DB_FILE):
        # 학번(01234 등) 앞자리 0이 날아가지 않도록 모두 문자열(str)로 읽어옵니다.
        return pd.read_csv(STUDENT_DB_FILE, dtype=str)
    else:
        return pd.DataFrame(columns=["학번", "이름", "수강과목"])

def save_student_db(df):
    # 한글 깨짐 방지를 위해 utf-8-sig 인코딩으로 저장합니다.
    df.to_csv(STUDENT_DB_FILE, index=False, encoding='utf-8-sig')

# 앱 실행 시 CSV 파일에서 데이터를 불러와 세션에 저장
if 'student_db' not in st.session_state:
    st.session_state.student_db = load_student_db()

# --- 페이지 기본 설정 ---
st.set_page_config(page_title="TA Agent - 문제 & TC 생성기", page_icon="🤖", layout="wide")

# --- 메모리(Session State) 초기화 ---
if 'problem_data' not in st.session_state:
    st.session_state.problem_data = None
if 'formatted_text' not in st.session_state:
    st.session_state.formatted_text = None
if 'test_cases' not in st.session_state:
    st.session_state.test_cases = None

# --- UI: 사이드바 ---
with st.sidebar:
    st.header("⚙️ 설정")
    api_key = st.text_input("Gemini API Key를 입력하세요", type="password")
    st.markdown("*(API 키는 서버에 저장되지 않습니다)*")

# --- 핵심 로직 1: 문제 생성 ---
def generate_problem(intent, category, is_template, difficulty, api_key):
    client = genai.Client(api_key=api_key)
    prompt = f"""
    당신은 대학교 컴퓨터공학과 C언어 전문 조교입니다.
    다음 요구사항에 맞추어 프로그래밍 과제 문제를 생성해주세요.

    [요구사항]
    - 출제 의도: {intent}
    - 카테고리: {category}
    - 난이도: {difficulty}
    - 템플릿 제공: {'제공함' if is_template else '제공하지 않음'}
    
    [제약사항]
    1. 수식이 필요한 경우 LaTeX 문법 사용
    2. '힌트'가 특별히 없다면 "없음"이라고 작성할 것
    3. 템플릿 제공 시, 학생이 구현할 부분만 비워둔 코드를 작성할 것
    4. 반드시 아래 JSON 스키마에 맞추어 답변할 것

    [JSON 스키마]
    {{
        "title": "문제 제목",
        "description": "문제 설명",
        "input_desc": "입력 형식 설명",
        "output_desc": "출력 형식 설명",
        "input_example": "입력 예시",
        "output_example": "출력 예시",
        "hint": "힌트",
        "solution_code": "완벽하게 동작하는 정답 C언어 코드",
        "template_code": "학생용 템플릿 코드"
    }}
    """
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json")
    )
    data = json.loads(response.text)
    formatted_text = f"/*\n{data['title']}\n\n문제 설명:\n{data['description']}\n\n입력 설명:\n{data['input_desc']}\n\n출력 설명:\n{data['output_desc']}\n\n입력 예시:\n{data['input_example']}\n\n출력 예시:\n{data['output_example']}\n\n힌트:\n{data['hint']}\n*/\n"
    return data, formatted_text

# --- 핵심 로직 2: 테스트케이스 생성 ---
def generate_tcs(problem_title, problem_desc, solution_code, api_key):
    client = genai.Client(api_key=api_key)
    prompt = f"""
    당신은 대학교 컴퓨터공학과 C언어 전문 조교입니다.
    아래 작성된 문제를 바탕으로 채점용 테스트케이스 총 20개(일반 15개, 엣지 5개)를 생성해주세요.

    [문제 제목]: {problem_title}
    [문제 설명]: {problem_desc}
    [정답 코드]: 
    {solution_code}
    """
    
    tc_schema = types.Schema(
        type=types.Type.ARRAY,
        description="20개의 테스트케이스 배열",
        items=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "case_type": types.Schema(type=types.Type.STRING, description="normal 또는 edge"),
                "reason": types.Schema(type=types.Type.STRING, description="테스트케이스 출제 이유"),
                "input": types.Schema(type=types.Type.STRING, description="입력 데이터 (줄바꿈은 \\n)"),
                "output": types.Schema(type=types.Type.STRING, description="예상되는 출력 데이터 (줄바꿈은 \\n)")
            },
            required=["case_type", "reason", "input", "output"]
        )
    )

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=tc_schema,
            max_output_tokens=8192
        )
    )
    return json.loads(response.text)

# --- 파일 자동 저장 로직 ---
def save_files_to_local(title, formatted_problem, template_code, solution_code, test_cases):
    safe_title = re.sub(r'[\\/*?:"<>|]', "", title).replace(" ", "_")
    base_dir = os.path.join(".", "Problems", safe_title)
    tc_dir = os.path.join(base_dir, "testcases")

    os.makedirs(tc_dir, exist_ok=True)

    with open(os.path.join(base_dir, "problem.c"), "w", encoding="utf-8") as f:
        f.write(formatted_problem)
        if template_code:
            f.write("\n" + template_code)
            
    with open(os.path.join(base_dir, "solution.c"), "w", encoding="utf-8") as f:
        f.write(formatted_problem + "\n" + solution_code)

    for i, tc in enumerate(test_cases, 1):
        with open(os.path.join(tc_dir, f"{i}.in"), "w", encoding="utf-8") as f:
            f.write(tc['input'])
        with open(os.path.join(tc_dir, f"{i}.out"), "w", encoding="utf-8") as f:
            f.write(tc['output'])
            
    return base_dir

# --- 템플릿 상세 분석 전용 로직 ---
def parse_log_data(log_content: str):
    SPLIT_TOKEN = "<<<SPLIT_MARK>>>"
    SPLIT_RE = re.compile(r"^-{54,}$")
    
    lines = log_content.splitlines()
    cleaned_lines = [SPLIT_TOKEN if SPLIT_RE.fullmatch(line.strip()) else line for line in lines]
    entries = "\n".join(cleaned_lines).split(SPLIT_TOKEN)
    
    parsed_data = {} 
    total_submissions = 0
    unique_probs = set()

    for entry in entries:
        parts = entry.strip().split("\n")
        if len(parts) <= 1: continue
        try:
            # 🌟 수정: 제출 결과(상태)를 같이 파싱합니다.
            user_id, problem_part, result = parts[0].strip().split(":", 2)
            prob_digits = "".join(filter(str.isdigit, problem_part))
            if prob_digits:
                prob_num = int(prob_digits)
                code = "\n".join(parts[1:]).strip()
                
                key = (user_id.strip(), prob_num)
                if key not in parsed_data:
                    parsed_data[key] = []
                
                # 🌟 핵심: 코드뿐만 아니라 '결과 상태(Compile Error 등)'도 함께 저장
                parsed_data[key].append({
                    "code": code, 
                    "result": result.strip()
                })
                
                total_submissions += 1
                unique_probs.add(prob_num)
        except ValueError:
            continue
            
    return parsed_data, total_submissions, sorted(list(unique_probs))

def get_marker_indices(code_lines):
    START_TAG = "// 이 위로 수정 금지"
    END_TAG = "// 이 아래로 수정 금지"
    start_idx, end_idx = None, None
    for idx, line in enumerate(code_lines):
        if START_TAG in line and start_idx is None: start_idx = idx
        if END_TAG in line: end_idx = idx
    return start_idx, end_idx

# 가독성 높은 Diff 생성기
def find_diff(base_lines, user_lines, line_offset=0):
    def norm(s): return " ".join(s.split())
    
    diff = difflib.ndiff([norm(l) for l in base_lines], [norm(l) for l in user_lines])
    base_line_num = 1 + line_offset
    changes = []
    
    for line in diff:
        if line.startswith('  '): 
            base_line_num += 1
        elif line.startswith('- '): 
            content = line[2:]
            if content.strip():  
                changes.append(f"- [원본 {base_line_num}번 줄 삭제/변경됨]: {content}")
            base_line_num += 1
        elif line.startswith('+ '): 
            content = line[2:]
            if content.strip():  
                changes.append(f"+ [학생 임의 추가/변경됨]: {content}")
            
    return changes

# ==========================================
# --- UI: 메인 화면 ---
# ==========================================
st.title("👨‍🏫 TA Agent: 자동 채점용 문제 & TC 생성기")
# 🌟 "학생 관리" 탭을 4번째에 추가합니다.
tab_gen, tab_grade, tab_diff, tab_student = st.tabs(["📝 문제 생성", "💯 자동 채점", "🔍 템플릿 훼손 상세 분석", "👥 학생 관리"])

# --- 탭 1: 문제 생성 ---
with tab_gen:
    with st.form("problem_form"):
        col1, col2 = st.columns(2)
        with col1:
            intent = st.text_input("출제 의도", placeholder="예: 조건문과 반복문 종합 응용")
            category = st.text_input("카테고리", placeholder="예: C언어 - 제어문")
        with col2:
            difficulty = st.selectbox("난이도", ["초급", "중급", "고급"])
            is_template = st.checkbox("학생용 템플릿 제공", value=True)
        
        submitted = st.form_submit_button("🚀 문제 및 테스트케이스 생성하기")

    if submitted:
        if not api_key:
            st.warning("👈 왼쪽 사이드바에 API Key를 먼저 입력해주세요!")
        elif not intent or not category:
            st.warning("출제 의도와 카테고리를 입력해주세요.")
        else:
            with st.spinner("1/2 단계: 문제 출제 중..."):
                p_data, f_text = generate_problem(intent, category, is_template, difficulty, api_key)
                st.session_state.problem_data = p_data
                st.session_state.formatted_text = f_text
                
            with st.spinner("2/2 단계: 테스트케이스 20개 생성 중 ..."):
                tcs = generate_tcs(p_data['title'], p_data['description'], p_data['solution_code'], api_key)
                if tcs is None:
                    st.error("❌ AI가 20개의 JSON 데이터를 생성하다가 문법 실수를 했습니다. 다시 한 번 눌러주세요!")
                else:
                    st.session_state.test_cases = tcs
                    st.success("✅ 모든 생성이 완료되었습니다!")

    if st.session_state.problem_data and st.session_state.test_cases:
        p_data = st.session_state.problem_data
        f_text = st.session_state.formatted_text
        tcs = st.session_state.test_cases

        st.divider()
        st.subheader("📝 1. 생성된 문제 및 코드")
        tab1_in, tab2_in, tab3_in = st.tabs(["📄 학생 배포용", "📝 템플릿", "💡 조교용 정답"])
        
        with tab1_in: st.code(f_text, language="c")
        with tab2_in: st.code(p_data['template_code'] if p_data['template_code'] else "// 템플릿 없음", language="c")
        with tab3_in: st.code(p_data['solution_code'], language="c")

        st.divider()
        st.subheader("🎯 2. 생성된 테스트케이스 20종")
        for i, tc in enumerate(tcs, 1):
            with st.expander(f"TC {i} ({tc['case_type']}) - {tc['reason']}"):
                c1, c2 = st.columns(2)
                with c1: st.code(tc['input'], language="text")
                with c2: st.code(tc['output'], language="text")

        st.divider()
        st.subheader("💾 3. VS Code 로컬 환경에 저장하기")
        if st.button("📁 파일 및 폴더 자동 생성 (클릭)"):
            try:
                saved_path = save_files_to_local(p_data['title'], f_text, p_data['template_code'], p_data['solution_code'], tcs)
                st.success(f"🎉 저장이 완료되었습니다! VS Code 탐색기에서 `{saved_path}` 경로를 확인해보세요!")
                st.balloons()
            except Exception as e:
                st.error(f"저장 중 오류 발생: {e}")


# ==========================================
# 탭 2: 채점 결과 파싱 및 엑셀 다운로드
# ==========================================
with tab_grade:
    st.header("📊 채점 결과 자동 정제 및 엑셀 다운로드")
    st.markdown("LMS 웹페이지의 표를 **엑셀에 먼저 붙여넣은 후**, 엑셀 표를 다시 복사하여 붙여넣어 주세요.")

    st.subheader("1. 채점 데이터 붙여넣기 (Ctrl+C / Ctrl+V)")
    st.info("💡 **빈칸 밀림 방지 꿀팁:** 웹에서 직접 복사하면 미제출(빈칸) 데이터가 사라져 열이 밀립니다. 반드시 **[웹 표 복사] → [엑셀에 붙여넣기] → [엑셀 표를 다시 복사] → [여기에 붙여넣기]** 해주세요!")
    
    raw_data = st.text_area("엑셀에서 복사한 표 데이터를 그대로 붙여넣어 주세요.", height=200, 
                            placeholder="여기에 표를 붙여넣으세요...")

    if raw_data:
        try:
            # 1. 엑셀에서 복사한 데이터(TSV 형식)를 DataFrame으로 바로 읽기
            df = pd.read_csv(io.StringIO(raw_data.strip()), sep='\t')
            
            # 탭 구분이 없는 경우(웹에서 직접 붙여넣은 경우) 경고 표시 및 비상 파싱
            if len(df.columns) <= 2:
                st.warning("⚠️ 열이 제대로 나뉘지 않았습니다. 혹시 웹에서 직접 붙여넣으셨다면, **엑셀을 한 번 거쳐서** 복사해주세요!")
                df = pd.read_csv(io.StringIO(raw_data.strip()), sep=r'\s+', engine='python')

            # 2. 문제 열(A, B, C...)이 시작되는 위치 찾기
            prob_start_idx = 6
            prob_cols = []
            for i, col in enumerate(df.columns):
                # 컬럼 이름이 알파벳 1글자인 경우 (A, B, C...)
                if len(str(col)) == 1 and str(col).isalpha():
                    if not prob_cols:
                        prob_start_idx = i
                    prob_cols.append(col)

            # 3. 문제 열(A, B, C...)의 데이터 정제 및 빈 행 삭제
            for col in prob_cols:
                # 엑셀 셀 내부에 포함된 줄바꿈(\n) 및 통과 시간 제거
                df[col] = df[col].astype(str).str.replace(r'[ \n\r]*\b\d{1,2}:\d{2}(?::\d{2})?\b', '', regex=True)
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 컬럼 반복문 밖에서 한 번에 처리하여 효율성 향상
            df = df.dropna(subset=['ID']).reset_index(drop=True)

            # 4. 하단 통계 행(점수 획득자, 통과자) 계산
            score_getters = [""] * len(df.columns)
            passers = [""] * len(df.columns)
            
            if len(df.columns) > 2:
                score_getters[2] = "점수 획득자 수"
                passers[2] = "통과자 수"
            
            for i, col in enumerate(df.columns):
                if col in prob_cols:
                    score_getters[i] = df[col].apply(lambda x: 1 if pd.notna(x) and x > 0 else 0).sum()
                    passers[i] = df[col].apply(lambda x: 1 if pd.notna(x) and x == 100 else 0).sum()
            
            summary_df = pd.DataFrame([score_getters, passers], columns=df.columns)
            final_df = pd.concat([df, summary_df], ignore_index=True)
            
            st.success("✅ 불규칙한 줄바꿈과 100점 문항에 붙은 시간을 완벽하게 교정했습니다!")
            st.dataframe(final_df, use_container_width=True)
            
            st.divider()

            # --- 여기서부터 레이아웃을 두 갈래로 나눕니다 ---
            col1, col2 = st.columns([1, 1])
            
            with col1:
                # 5. 엑셀 다운로드 영역
                st.subheader("2. 엑셀 다운로드")
                st.info("💡 전체 성적표 데이터를 엑셀로 저장합니다.")
                
                excel_buffer = io.BytesIO()
                final_df.fillna("").to_excel(excel_buffer, index=False, engine='openpyxl')
                
                st.download_button(
                    label="💾 정제된 성적표 다운로드",
                    data=excel_buffer.getvalue(),
                    file_name="cleaned_grades.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary"
                )

            with col2:
                # 6. 총득점 요약 및 복사용 표 영역
                st.subheader("3. 총득점 및 평균 (복사용)")
                
                # 회차 이름 입력 (이미지처럼 원하는 제목을 달 수 있습니다)
                col_name = st.text_input("복사할 열의 제목을 입력하세요", value="0316-1회차")
                
                # '총득점' 데이터를 숫자형으로 변환 후 리스트로 추출
                scores = pd.to_numeric(df['총득점'], errors='coerce').dropna()
                
                # 평균 계산 (소수점 1자리까지 반올림)
                avg_score = round(scores.mean(), 1)
                
                # 리스트 끝에 평균 점수 추가
                copy_data = scores.tolist()
                copy_data.append(avg_score)
                
                # 복사용 데이터프레임 생성
                copy_df = pd.DataFrame({col_name: copy_data})
                
                # 화면에 출력 (hide_index=True로 왼쪽에 번호가 안 뜨게 하여 복사하기 쉽게 만듦)
                st.dataframe(copy_df, hide_index=True, use_container_width=True)
                st.caption("💡 표 안의 데이터를 쭉 드래그해서 복사(Ctrl+C)하세요.")

        except Exception as e:
            st.error(f"데이터 파싱 중 예상치 못한 오류가 발생했습니다: {e}")

# ==========================================
# 탭 3: 템플릿 훼손 및 필수 구현 함수 종합 분석
# ==========================================
with tab_diff:
    st.header("🔍 종합 템플릿 & 필수 함수 분석기")
    st.markdown("가장 먼저 학생들의 코드가 담긴 **원본 로그 파일**을 업로드하여 분석을 시작하세요.")
    
    log_file = st.file_uploader("📂 1단계: 원본 로그 파일 업로드", type=["txt"], help="logs-XXXX.txt 파일을 올려주세요.")
    
    if log_file:
        log_content = log_file.getvalue().decode('utf-8-sig')
        student_codes, total_subs, unique_probs = parse_log_data(log_content)
        
        st.success(f"✅ **로그 분석 완료!** (총 제출: **{total_subs}**건 / 포함된 문제: **{len(unique_probs)}**개 ➡️ {unique_probs})")
        st.divider()
        
        st.markdown("#### ⚙️ 2단계: 분석할 대상 문제 선택 및 템플릿 코드 입력")
        
        col_prob, col_code = st.columns([1, 4])
        with col_prob:
            target_prob_num = st.selectbox("📌 분석할 대상 문제 번호", unique_probs)
        
        with col_code:
            template_code_input = st.text_area(f"이곳에 [{target_prob_num}번] 문제의 원본 템플릿(.c) 소스코드를 복사해서 붙여넣으세요.", height=250)
            
        st.markdown("#### 🛠️ 3단계: 필수 구현 함수(키워드) 검사 (선택사항)")
        required_funcs_input = st.text_input(
            "학생이 반드시 구현해야 하는 함수명을 쉼표(,)로 구분해 적어주세요.", 
            placeholder="예: push, pop, is_empty, is_full"
        )
        
        if st.button(f"🚀 {target_prob_num}번 문제 종합 상세 분석 시작", type="primary"):
            if not template_code_input.strip():
                st.warning("👆 원본 템플릿 코드를 입력해주세요!")
            else:
                with st.spinner("모든 학생의 제출 내역을 템플릿 및 필수 함수 조건과 정밀 비교하고 있습니다..."):
                    
                    base_lines = template_code_input.strip().splitlines()
                    base_start, base_end = get_marker_indices(base_lines)
                    
                    required_funcs = [f.strip() for f in required_funcs_input.split(',')] if required_funcs_input.strip() else []
                    
                    if None in (base_start, base_end):
                        st.error("❌ 입력하신 원본 템플릿에 '// 이 위로(아래로) 수정 금지' 주석이 없습니다.")
                    else:
                        st.divider()
                        st.subheader(f"🚨 {target_prob_num}번 문제 적발 목록 (에러 제출건 제외)")
                        
                        fault_count = 0
                        
                        for (user_id, prob_num), codes in student_codes.items():
                            if prob_num != int(target_prob_num):
                                continue
                                
                            user_faults = []
                            last_inspected_idx = -1 
                            
                            for idx, sub_data in enumerate(codes):
                                user_code_str = sub_data["code"]
                                result_status = sub_data["result"].lower()
                                
                                if "compile error" in result_status or "compiler error" in result_status or "시간제한" in result_status:
                                    continue
                                    
                                last_inspected_idx = idx + 1
                                user_lines = user_code_str.splitlines()
                                user_start, user_end = get_marker_indices(user_lines)
                                
                                if None in (user_start, user_end):
                                    user_faults.append({
                                        "sub_idx": idx + 1,
                                        "type": "마커 인식 실패",
                                        "top_diff": [],
                                        "bottom_diff": [],
                                        "missing_funcs": []
                                    })
                                    continue
                                    
                                base_top = base_lines[:base_start]
                                user_top = user_lines[:user_start]
                                base_bottom = base_lines[base_end+1:]
                                user_bottom = user_lines[user_end+1:]
                                
                                top_violates = "".join("".join(base_top).split()) != "".join("".join(user_top).split())
                                bottom_violates = "".join("".join(base_bottom).split()) != "".join("".join(user_bottom).split())
                                
                                missing_funcs = []
                                for func in required_funcs:
                                    if not re.search(r'\b' + re.escape(func) + r'\b', user_code_str):
                                        missing_funcs.append(func)
                                
                                if top_violates or bottom_violates or missing_funcs:
                                    fault_types = []
                                    if top_violates: fault_types.append("위쪽 훼손")
                                    if bottom_violates: fault_types.append("아래쪽 훼손")
                                    if missing_funcs: fault_types.append("필수 함수 미구현")
                                    
                                    user_faults.append({
                                        "sub_idx": idx + 1,
                                        "type": " & ".join(fault_types),
                                        "top_diff": find_diff(base_top, user_top) if top_violates else [],
                                        "bottom_diff": find_diff(base_bottom, user_bottom, line_offset=base_end+1) if bottom_violates else [],
                                        "missing_funcs": missing_funcs
                                    })
                                    
                            if user_faults:
                                fault_count += 1
                                latest = user_faults[-1]
                                total_subs = len(codes)
                                
                                title = f"❌ {user_id} - [문제 {prob_num}] ({latest['type']})"
                                with st.expander(title):
                                    
                                    if latest['sub_idx'] != last_inspected_idx:
                                        st.success(f"ℹ️ 이 학생은 총 {total_subs}번 제출했으며, **최종 유효 제출본(에러 제외)에서는 모든 규정을 지켰습니다.** (과거 {latest['sub_idx']}번째 제출 기준 위반)")
                                    else:
                                        st.warning(f"⚠️ 이 학생은 총 {total_subs}번 제출했으며, **최종 유효 제출본(에러 제외)에서도 여전히 위반 사항이 존재**합니다.")
                                        
                                    if "마커 인식 실패" in latest['type']:
                                        st.error("⚠️ 학생이 '// 이 위로(아래로) 수정 금지' 주석 자체를 지웠거나 변형했습니다.")
                                    
                                    if latest['missing_funcs']:
                                        st.error(f"🚨 **출제 의도 위반 (필수 함수 누락):** `{', '.join(latest['missing_funcs'])}` 함수가 구현되지 않았거나 이름을 틀렸습니다.")
                                        
                                    if latest['top_diff']:
                                        st.markdown(f"##### 🔼 위쪽 템플릿 변경 사항 (총 {total_subs}번 중 {latest['sub_idx']}번째 제출 기준)")
                                        st.code("\n".join(latest['top_diff']), language="diff")
                                    if latest['bottom_diff']:
                                        st.markdown(f"##### 🔽 아래쪽 템플릿 변경 사항 (총 {total_subs}번 중 {latest['sub_idx']}번째 제출 기준)")
                                        st.code("\n".join(latest['bottom_diff']), language="diff")
                        
                        if fault_count == 0:
                            st.success(f"🎉 {target_prob_num}번 문제의 템플릿을 훼손하거나 필수 함수를 누락한 학생이 한 명도 없습니다!")
                        else:
                            st.info(f"총 {fault_count}명의 규정 위반 학생을 적발했습니다. (컴파일 에러 및 시간 초과 제출건은 제외됨)")

    st.divider()
    # 🌟 새롭게 추가된 기능: 의심스러운 붙여넣기 탐지 🌟
    st.header("🕵️‍♂️ 붙여넣기(Paste) 부정행위 탐지기")
    st.markdown("에디터 활동 로그(CSV)를 업로드하여, 비정상적으로 긴 코드를 복사하여 붙여넣은 내역을 탐지합니다.")
    
    action_csv = st.file_uploader("📂 행동 로그 파일 업로드 (CSV)", type=["csv"], help="user_id, action, data, additional_data 열이 포함된 CSV 파일을 올려주세요.")
    
    if action_csv:
        try:
            df_action = pd.read_csv(action_csv, dtype=str)
            if not {'user_id', 'action', 'data', 'additional_data'}.issubset(df_action.columns):
                st.error("❌ CSV 파일에 필수 열(user_id, action, data, additional_data)이 모두 포함되어 있지 않습니다.")
            else:
                # '붙여넣기' 동작만 필터링
                paste_df = df_action[df_action['action'].str.contains('붙여넣기', na=False)].copy()
                
                suspicious_records = []
                for _, row in paste_df.iterrows():
                    pasted_text = str(row['data']) if pd.notna(row['data']) else ""
                    
                    # 단순 #include 나 불필요한 공백 제거 후 순수 코드 길이 측정
                    clean_text = re.sub(r'#include\s*[<"].*?[>"]', '', pasted_text).strip()
                    
                    # 짧은 단어(is_empty 등)는 무시하고 의미 있는 길이(40자 이상)의 블록을 붙여넣었을 때만 의심 처리
                    if len(clean_text) >= 40: 
                        suspicious_records.append(row)
                        
                if not suspicious_records:
                    st.success("✅ 비정상적인 붙여넣기(부정행위 의심) 내역이 발견되지 않았습니다!")
                else:
                    st.warning(f"⚠️ 총 {len(suspicious_records)}건의 의심스러운 긴 코드 붙여넣기가 적발되었습니다!")
                    
                    for idx, row in enumerate(suspicious_records, 1):
                        uid = row.get('user_id', '알수없음')
                        pid = row.get('problem_id', '알수없음')
                        time_val = row.get('timestamp', '시간없음')
                        data_val = str(row.get('data', ''))
                        add_data_val = str(row.get('additional_data', ''))
                        
                        with st.expander(f"🚨 [{uid}] - 문제 {pid} (시간: {time_val})"):
                            st.markdown("**📌 실제로 붙여넣은 내용 (`data`)**")
                            st.code(data_val, language="c")
                            
                            st.markdown("**📝 당시 전체 코드 상태 (`additional_data`)**")
                            st.code(add_data_val, language="c")
                            
        except Exception as e:
            st.error(f"CSV 파일을 읽거나 분석하는 중 오류가 발생했습니다: {e}")


# ==========================================
# 탭 4: 학생 관리 시스템 (영구 저장 / CSV 연동)
# ==========================================
with tab_student:
    st.header("👥 수강생 관리 시스템")
    st.markdown("여기에 등록된 학생 데이터는 `students.csv` 파일에 영구적으로 안전하게 보관됩니다.")

    col_add, col_bulk = st.columns(2)
    
    with col_add:
        st.subheader("➕ 개별 학생 추가")
        with st.form("add_student_form", clear_on_submit=True):
            new_id = st.text_input("학번 *", placeholder="예: DS202403024")
            new_name = st.text_input("이름 *", placeholder="예: 홍길동")
            new_course = st.text_input("수강과목 *", placeholder="예: 자료구조 1분반")
            
            submit_add = st.form_submit_button("학생 추가하기", type="primary")
            
            if submit_add:
                if not new_id.strip() or not new_name.strip() or not new_course.strip():
                    st.warning("⚠️ 학번, 이름, 수강과목을 모두 입력해주세요.")
                elif new_id in st.session_state.student_db['학번'].values:
                    st.error(f"❌ 이미 등록된 학번({new_id})입니다.")
                else:
                    new_data = pd.DataFrame([{"학번": new_id, "이름": new_name, "수강과목": new_course}])
                    st.session_state.student_db = pd.concat([st.session_state.student_db, new_data], ignore_index=True)
                    # 🌟 핵심: 추가된 데이터를 CSV 파일에 즉시 영구 저장!
                    save_student_db(st.session_state.student_db)
                    
                    st.success(f"✅ {new_name}({new_id}) 학생이 성공적으로 등록되었습니다!")
                    st.rerun()
                    
    with col_bulk:
        st.subheader("📂 명렬표 파일로 일괄 등록")
        st.info("💡 학번, 이름, 수강과목 열(Column)이 포함된 CSV 파일을 올리면 한 번에 등록됩니다.")
        uploaded_csv = st.file_uploader("CSV 명렬표 업로드", type=["csv"])
        
        if uploaded_csv is not None:
            if st.button("일괄 등록 실행하기", type="primary"):
                try:
                    bulk_df = pd.read_csv(uploaded_csv, dtype=str)
                    if set(["학번", "이름", "수강과목"]).issubset(bulk_df.columns):
                        # 기존 데이터와 병합하고 중복 학번 제거
                        st.session_state.student_db = pd.concat([st.session_state.student_db, bulk_df]).drop_duplicates(subset=['학번'], keep='last').reset_index(drop=True)
                        # 🌟 핵심: 일괄 추가된 데이터를 CSV 파일에 영구 저장!
                        save_student_db(st.session_state.student_db)
                        
                        st.success(f"✅ 총 {len(bulk_df)}명의 데이터가 일괄 등록/업데이트되었습니다!")
                        st.rerun()
                    else:
                        st.error("❌ 업로드한 파일에 '학번', '이름', '수강과목' 열이 모두 존재해야 합니다.")
                except Exception as e:
                    st.error(f"파일을 읽는 중 오류가 발생했습니다: {e}")

    st.divider()

    # --- 학생 목록 및 다운로드 출력 영역 ---
    st.subheader(f"📋 등록된 학생 목록 (총 {len(st.session_state.student_db)}명)")
    if st.session_state.student_db.empty:
        st.warning("현재 등록된 학생이 없습니다. 위에서 학생을 추가해 주세요.")
    else:
        st.dataframe(st.session_state.student_db, use_container_width=True, hide_index=True)
        
        # 엑셀로 볼 수 있도록 CSV 다운로드 버튼 제공
        csv_data = st.session_state.student_db.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
        st.download_button(
            label="💾 현재 학생 목록 다운로드 (Excel용 CSV)",
            data=csv_data,
            file_name="students_backup.csv",
            mime="text/csv",
            type="secondary"
        )

    st.divider()

    # --- 학생 삭제 영역 ---
    st.subheader("🗑️ 학생 삭제")
    if not st.session_state.student_db.empty:
        col_del, col_btn = st.columns([3, 1])
        with col_del:
            # 등록된 학생 목록을 보기 좋게 "학번 - 이름" 형태로 드롭다운 제공
            display_list = st.session_state.student_db.apply(lambda row: f"{row['학번']} - {row['이름']}", axis=1).tolist()
            del_selection = st.selectbox("삭제할 학생을 선택하세요", display_list)
            
        with col_btn:
            st.markdown("<br>", unsafe_allow_html=True) 
            if st.button("선택한 학생 삭제", type="secondary"):
                del_id = del_selection.split(" - ")[0] # 학번만 추출
                st.session_state.student_db = st.session_state.student_db[st.session_state.student_db['학번'] != del_id]
                
                # 🌟 핵심: 삭제된 후의 데이터를 CSV 파일에 영구 저장!
                save_student_db(st.session_state.student_db)
                
                st.success(f"✅ {del_selection} 학생 데이터가 삭제되었습니다.")
                st.rerun()
    else:
        st.write("삭제할 학생 데이터가 없습니다.")