from google import genai
from google.genai import types
import json

# 1. API 키 설정 (발급받은 키를 입력하세요)
API_KEY = "AIzaSyBboIIXbUigrDd7nzNotnN-MBxIq8IuDSs" 

# 새로운 Client 객체 생성 방식
client = genai.Client(api_key=API_KEY)

# 2. 문제 생성 및 템플릿 포매팅 함수
def generate_problem_formatted(intent, category, is_template, difficulty):
    prompt = f"""
    당신은 대학교 컴퓨터공학과 C언어 전문 조교입니다.
    다음 요구사항에 맞추어 프로그래밍 과제 문제를 생성해주세요.

    [요구사항]
    - 출제 의도: {intent}
    - 카테고리: {category}
    - 난이도: {difficulty}
    - 템플릿 제공 여부: {'제공함' if is_template else '제공하지 않음'}
    
    [제약사항]
    1. 수식이 필요한 경우 LaTeX 문법 사용 (예: $O(N)$, $x_i$)
    2. '힌트'가 특별히 없다면 "없음"이라고 작성할 것
    3. 템플릿 제공 여부가 '제공함'일 경우, 학생이 구현할 부분만 비워둔 코드를 작성할 것
    4. 반드시 아래 JSON 스키마에 맞추어 답변할 것

    [JSON 스키마]
    {{
        "title": "문제 제목",
        "description": "문제 설명",
        "input_desc": "입력 형식 설명",
        "output_desc": "출력 형식 설명",
        "input_example": "입력 예시 데이터 (실제 값만 기재)",
        "output_example": "출력 예시 데이터 (실제 값만 기재)",
        "hint": "문제 해결을 위한 힌트 (없을 경우 '없음')",
        "solution_code": "완벽하게 동작하는 정답 C언어 코드",
        "template_code": "학생용 템플릿 코드 (제공하지 않을 경우 빈 문자열)"
    }}
    """

    # 새로운 API 호출 방식 (최신 모델인 gemini-2.5-flash 적용)
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )
    
    data = json.loads(response.text)

    # 3. 요청하신 템플릿 양식으로 텍스트 조립
    formatted_text = f"""/*
{data['title']}

문제 설명:
{data['description']}

입력 설명:
{data['input_desc']}

출력 설명:
{data['output_desc']}

입력 예시:
{data['input_example']}

출력 예시:
{data['output_example']}

힌트:
{data['hint']}
*/
"""
    return data, formatted_text

# 4. 실행 및 결과 확인
if __name__ == "__main__":
    print("문제를 생성하고 포매팅하는 중입니다...\n")
    
    raw_data, formatted_problem_block = generate_problem_formatted(
        intent="동적 배열 할당과 포인터 연산의 이해",
        category="C언어 - 포인터와 배열",
        is_template=True,
        difficulty="중급"
    )

    print("========= 학생 배포용 파일 구성 =========")
    print(formatted_problem_block) 
    
    if raw_data['template_code']:
        print(raw_data['template_code']) 
    else:
        print("// 이 문제는 템플릿 코드가 제공되지 않습니다. 처음부터 작성하세요.")
        
    print("\n========= 조교용 정답 파일 구성 =========")
    print(formatted_problem_block)
    print(raw_data['solution_code'])