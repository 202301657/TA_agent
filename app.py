import streamlit as st
from google import genai
from google.genai import types
import json
import os
import re
import time

# --- 페이지 기본 설정 ---
st.set_page_config(page_title="TA Agent - 문제 & TC 생성기", page_icon="🤖", layout="wide")

# --- 메모리(Session State) 초기화 ---
# 새로고침 되어도 데이터가 날아가지 않도록 저장 공간을 만듭니다.
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

# --- 핵심 로직 2: 테스트케이스 생성 (20개) - 문법 실수 원천 차단 적용 ---
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
    
    # 🌟 핵심: AI가 절대 어길 수 없는 완벽한 JSON 틀(Schema)을 시스템에 강제합니다.
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

    # API 호출 시 틀(Schema)을 같이 던져줍니다.
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=tc_schema, # <--- 바로 이 부분이 문법 실수를 100% 막아줍니다!
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

# ==========================================
# --- UI: 메인 화면 ---
# ==========================================
st.title("👨‍🏫 TA Agent: 자동 채점용 문제 & TC 생성기")

with st.form("problem_form"):
    col1, col2 = st.columns(2)
    with col1:
        intent = st.text_input("출제 의도", placeholder="예: 조건문과 반복문 종합 응용")
        category = st.text_input("카테고리", placeholder="예: C언어 - 제어문")
    with col2:
        difficulty = st.selectbox("난이도", ["초급", "중급", "고급"])
        is_template = st.checkbox("학생용 템플릿 제공", value=True)
    
    submitted = st.form_submit_button("🚀 문제 및 테스트케이스 생성하기")

# '생성하기' 버튼을 눌렀을 때만 API를 호출하고 결과를 세션에 저장
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
                # 에러가 나도 빨간 화면 대신 아래의 친절한 경고창이 뜹니다.
                st.error("❌ AI가 20개의 JSON 데이터를 생성하다가 문법 실수를 했습니다. '생성하기' 버튼을 다시 한 번 눌러주세요!")
            else:
                st.session_state.test_cases = tcs
                st.success("✅ 모든 생성이 완료되었습니다!")

# --- 세션에 저장된 데이터가 있다면 화면에 출력하고 저장 버튼 표시 ---
if st.session_state.problem_data and st.session_state.test_cases:
    p_data = st.session_state.problem_data
    f_text = st.session_state.formatted_text
    tcs = st.session_state.test_cases

    st.divider()
    st.subheader("📝 1. 생성된 문제 및 코드")
    tab1, tab2, tab3 = st.tabs(["📄 학생 배포용", "📝 템플릿", "💡 조교용 정답"])
    
    with tab1: st.code(f_text, language="c")
    with tab2: st.code(p_data['template_code'] if p_data['template_code'] else "// 템플릿 없음", language="c")
    with tab3: st.code(p_data['solution_code'], language="c")

    st.divider()
    st.subheader("🎯 2. 생성된 테스트케이스 20종")
    for i, tc in enumerate(tcs, 1):
        with st.expander(f"TC {i} ({tc['case_type']}) - {tc['reason']}"):
            c1, c2 = st.columns(2)
            with c1: st.code(tc['input'], language="text")
            with c2: st.code(tc['output'], language="text")

    st.divider()
    st.subheader("💾 3. VS Code 로컬 환경에 저장하기")
    
    # 이 버튼을 눌러도 session_state 덕분에 데이터가 날아가지 않습니다.
    if st.button("📁 파일 및 폴더 자동 생성 (클릭)"):
        try:
            saved_path = save_files_to_local(p_data['title'], f_text, p_data['template_code'], p_data['solution_code'], tcs)
            st.success(f"🎉 저장이 완료되었습니다! VS Code 탐색기에서 `{saved_path}` 경로를 확인해보세요!")
            st.balloons()
        except Exception as e:
            st.error(f"저장 중 오류 발생: {e}")