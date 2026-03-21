import difflib
from pathlib import Path
from typing import List, Tuple, Optional
import re

# 기존 파싱 함수와 동일한 로직 사용
SPLIT_TOKEN = "<<<SPLIT_MARK>>>"
SPLIT_RE = re.compile(rf"^-{{54,}}$")
START_TAG = "// 이 위로 수정 금지"
END_TAG = "// 이 아래로 수정 금지"

BASE_DIR = Path(__file__).resolve().parent
CONTEST_NUMBER = 1004  # 대회 번호에 맞게 수정하세요
LOG_FILE = BASE_DIR / f"logs-{CONTEST_NUMBER}.txt"
ORIGINAL_PROBLEM_DIR = BASE_DIR / "original_problem"

def parse_log_file(path: Path):
    # (이전과 동일한 파싱 로직, Compile Error 필터링 제외하여 모두 불러옴)
    with path.open("r", encoding="utf-8") as f:
        lines = f.readlines()
    cleaned_lines = [SPLIT_TOKEN + "\n" if SPLIT_RE.fullmatch(line.strip()) else line for line in lines]
    entries = "".join(cleaned_lines).strip().split(SPLIT_TOKEN)
    
    parsed = []
    for entry in entries:
        lines = entry.strip().split("\n")
        if len(lines) <= 1: continue
        try:
            user_id, problem_part, result = lines[0].strip().split(":", 2)
            problem_digits = "".join(filter(str.isdigit, problem_part))
            if not problem_digits: continue
            code = "\n".join(lines[1:]).strip()
            parsed.append((user_id.strip(), int(problem_digits), result.strip(), code))
        except ValueError:
            continue
    return parsed

def get_marker_indices(code_lines: List[str]) -> Tuple[Optional[int], Optional[int]]:
    start_idx, end_idx = None, None
    for idx, line in enumerate(code_lines):
        if START_TAG in line and start_idx is None: start_idx = idx
        if END_TAG in line: end_idx = idx
    return start_idx, end_idx

def find_modified_lines(base_lines: List[str], user_lines: List[str], line_offset: int = 0) -> List[str]:
    """difflib을 이용해 템플릿(base)에서 삭제/변경된 줄 번호와 내용을 찾습니다."""
    diff = difflib.ndiff(base_lines, user_lines)
    base_line_num = 1 + line_offset
    changes = []
    
    for line in diff:
        if line.startswith('  '):  # 변경 없음
            base_line_num += 1
        elif line.startswith('- '):  # 템플릿에 있던 코드가 삭제되거나 수정됨
            changes.append(f"  -> {base_line_num}번째 줄 수정됨: {line[2:].strip()}")
            base_line_num += 1
        elif line.startswith('+ '):  # 학생이 임의로 추가한 코드
            pass # (필요하다면 추가된 코드도 잡을 수 있습니다)
            
    return changes

def main():
    submissions = parse_log_file(LOG_FILE)
    
    print(f"📊 [대회 {CONTEST_NUMBER}] 템플릿 외부 수정 상세 리포트\n" + "="*50)
    
    for user_id, problem_number, judge_result, user_code in submissions:
        base_path = ORIGINAL_PROBLEM_DIR / f"{problem_number}.c"
        if not base_path.exists():
            continue
            
        base_code = base_path.read_text(encoding="utf-8")
        base_lines = base_code.splitlines()
        user_lines = user_code.splitlines()
        
        base_start, base_end = get_marker_indices(base_lines)
        user_start, user_end = get_marker_indices(user_lines)
        
        # 1. 마커 인식 실패
        if None in (base_start, base_end, user_start, user_end):
            print(f"[{problem_number}번 문제] {user_id} - 수정 금지 마커 인식 실패 (삭제 또는 훼손됨)")
            continue
            
        # 2. 위쪽 변경 추적
        base_top = base_lines[:base_start]
        user_top = user_lines[:user_start]
        top_changes = find_modified_lines(base_top, user_top, line_offset=0)
        
        # 3. 아래쪽 변경 추적
        base_bottom = base_lines[base_end + 1:]
        user_bottom = user_lines[user_end + 1:]
        bottom_changes = find_modified_lines(base_bottom, user_bottom, line_offset=base_end + 1)
        
        if top_changes or bottom_changes:
            print(f"[{problem_number}번 문제] {user_id} - 템플릿 훼손 발견!")
            if top_changes:
                print(" [위쪽 변경]")
                print("\n".join(top_changes))
            if bottom_changes:
                print(" [아래쪽 변경]")
                print("\n".join(bottom_changes))
            print("-" * 30)

if __name__ == "__main__":
    main()