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

# --- 템플릿 상세 분석 전용 로직 (완전 개편) ---
def parse_log_data(log_content: str):
    SPLIT_TOKEN = "<<<SPLIT_MARK>>>"
    SPLIT_RE = re.compile(r"^-{54,}$")
    
    lines = log_content.splitlines()
    cleaned_lines = [SPLIT_TOKEN if SPLIT_RE.fullmatch(line.strip()) else line for line in lines]
    entries = "\n".join(cleaned_lines).split(SPLIT_TOKEN)
    
    parsed_data = {} # (user_id, prob_num) -> list of codes (모든 제출 기록 보존)
    total_submissions = 0
    unique_probs = set()

    for entry in entries:
        parts = entry.strip().split("\n")
        if len(parts) <= 1: continue
        try:
            user_id, problem_part, result = parts[0].strip().split(":", 2)
            prob_digits = "".join(filter(str.isdigit, problem_part))
            if prob_digits:
                prob_num = int(prob_digits)
                code = "\n".join(parts[1:]).strip()
                
                key = (user_id.strip(), prob_num)
                if key not in parsed_data:
                    parsed_data[key] = []
                # 덮어쓰지 않고 모든 제출 기록을 리스트에 누적 저장
                parsed_data[key].append(code)
                
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

tab_gen, tab_grade, tab_diff = st.tabs(["📝 문제 생성", "💯 자동 채점", "🔍 템플릿 훼손 상세 분석"])

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

# --- 탭 2: 자동 채점 ---
with tab_grade:
    st.info("여기는 앞서 안내해 드린 자동 채점(스프레드시트 연동) 탭이 들어갈 자리입니다.")

# ==========================================
# 탭 3: 템플릿 훼손 및 필수 구현 함수 종합 분석
# ==========================================
with tab_diff:
    st.header("🔍 종합 템플릿 & 필수 함수 분석기")
    st.markdown("가장 먼저 학생들의 코드가 담긴 **원본 로그 파일**을 업로드하여 분석을 시작하세요.")
    
    # [Step 1] 원본 로그 파일 업로드
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
                    
                    # 필수 구현 함수 리스트 파싱
                    required_funcs = [f.strip() for f in required_funcs_input.split(',')] if required_funcs_input.strip() else []
                    
                    if None in (base_start, base_end):
                        st.error("❌ 입력하신 원본 템플릿에 '// 이 위로(아래로) 수정 금지' 주석이 없습니다.")
                    else:
                        st.divider()
                        st.subheader(f"🚨 {target_prob_num}번 문제 적발 목록 (템플릿 훼손 및 필수 함수 미구현)")
                        
                        fault_count = 0
                        
                        # 학생별로 모든 제출 코드를 순회
                        for (user_id, prob_num), codes in student_codes.items():
                            if prob_num != int(target_prob_num):
                                continue
                                
                            user_faults = []
                            
                            for idx, user_code_str in enumerate(codes):
                                user_lines = user_code_str.splitlines()
                                user_start, user_end = get_marker_indices(user_lines)
                                
                                # 1. 마커 인식 실패
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
                                
                                # 2. 템플릿 훼손 검사 (공백 완벽 무시)
                                top_violates = "".join("".join(base_top).split()) != "".join("".join(user_top).split())
                                bottom_violates = "".join("".join(base_bottom).split()) != "".join("".join(user_bottom).split())
                                
                                # 3. 필수 구현 함수 존재 여부 검사 (단어 단위 매칭)
                                missing_funcs = []
                                for func in required_funcs:
                                    if not re.search(r'\b' + re.escape(func) + r'\b', user_code_str):
                                        missing_funcs.append(func)
                                
                                # 훼손이 있거나 필수 함수가 빠졌다면 기록
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
                                    
                            # 해당 학생이 한 번이라도 규정을 위반한 적이 있다면 화면에 출력
                            if user_faults:
                                fault_count += 1
                                latest = user_faults[-1] # 가장 마지막에 적발된 내역
                                total_subs = len(codes)
                                
                                title = f"❌ {user_id} - [문제 {prob_num}] ({latest['type']})"
                                with st.expander(title):
                                    
                                    # 최종 제출본에서는 규정을 지켰는지 조교에게 안내
                                    if latest['sub_idx'] != total_subs:
                                        st.success(f"ℹ️ 이 학생은 총 {total_subs}번 제출했으며, **최종 제출본에서는 모든 규정(템플릿 복구, 함수 구현)을 지켰습니다.** (아래는 과거 {latest['sub_idx']}번째 제출 기준 위반 내역입니다.)")
                                    else:
                                        st.warning(f"⚠️ 이 학생은 총 {total_subs}번 제출했으며, **최종 제출본에서도 여전히 위반 사항이 존재**합니다.")
                                        
                                    if "마커 인식 실패" in latest['type']:
                                        st.error("⚠️ 학생이 '// 이 위로(아래로) 수정 금지' 주석 자체를 지웠거나 변형했습니다.")
                                    
                                    # 누락된 함수가 있으면 강조해서 출력
                                    if latest['missing_funcs']:
                                        st.error(f"🚨 **출제 의도 위반 (필수 함수 누락):** `{', '.join(latest['missing_funcs'])}` 함수가 구현되지 않았거나 이름을 틀렸습니다.")
                                        
                                    if latest['top_diff']:
                                        st.markdown(f"##### 🔼 위쪽 템플릿 변경 사항")
                                        st.code("\n".join(latest['top_diff']), language="diff")
                                    if latest['bottom_diff']:
                                        st.markdown(f"##### 🔽 아래쪽 템플릿 변경 사항")
                                        st.code("\n".join(latest['bottom_diff']), language="diff")
                        
                        if fault_count == 0:
                            st.success(f"🎉 {target_prob_num}번 문제의 템플릿을 훼손하거나 필수 함수를 누락한 학생이 한 명도 없습니다!")
                        else:
                            st.info(f"총 {fault_count}명의 규정 위반 학생을 적발했습니다. (템플릿 훼손 및 필수 구현 함수 누락)")