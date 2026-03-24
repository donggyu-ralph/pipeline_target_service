# Error Log Agent - 개선 작업 내역

## 작업 일자: 2026-03-23

### 1. 파일 변경 사항 추적 개선

#### 문제
- Slack 보고서에서 표시되는 "수정된 파일 목록"과 실제 Git diff의 파일 목록이 일치하지 않음
- Slack 보고서: `src/config.py`, `src/database.py` 등 여러 파일
- Git diff: `.idea/vcs.xml`, `logs/app.log`만 표시

#### 원인
- `source_code_context.keys()`를 사용하여 **분석을 위해 읽은 모든 파일**을 표시
- 실제로 **수정된 파일**만 추적하지 않음

#### 해결
**파일: `/Users/donggyu/error-log_agent/src/agent/nodes/code_fixer.py`**

```python
# Line 192, 229: actually_modified_files 리스트 추가
files_modified = 0
actually_modified_files = []  # Track actually written files

for file_path, content in source_code_context.items():
    fixed_content = apply_code_fix(file_path, content, fix_description, llm)

    if fixed_content:
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(fixed_content, encoding="utf-8")
            files_modified += 1
            actually_modified_files.append(file_path)  # 실제 쓰기 성공한 파일만 추가
        except Exception as e:
            logger.error("file_write_failed", file_path=file_path, error=str(e))
```

**파일: `/Users/donggyu/error-log_agent/src/agent/nodes/code_fixer.py`**

```python
# Line 121-168: commit_changes 함수에 modified_files 파라미터 추가
def commit_changes(message: str, project_root: str, modified_files: list[str] | None = None) -> Optional[str]:
    """Commit changes to git.

    Only stages the files that were actually modified by the agent.
    Falls back to staging all tracked changes if no file list is provided.
    """
    try:
        import git
        repo = git.Repo(project_root)

        if modified_files:
            # Resolve paths relative to project root for git staging
            project_path = Path(project_root).resolve()
            files_to_stage = []
            for f in modified_files:
                p = Path(f)
                if p.is_absolute():
                    try:
                        files_to_stage.append(str(p.relative_to(project_path)))
                    except ValueError:
                        files_to_stage.append(f)
                else:
                    files_to_stage.append(f)

            logger.info("git_staging_files", files=files_to_stage)
            repo.index.add(files_to_stage)
        else:
            # Fallback: stage only tracked file changes
            changed = [item.a_path for item in repo.index.diff(None)]
            if changed:
                repo.index.add(changed)

        commit = repo.index.commit(message)
        return commit.hexsha
```

```python
# Line 238: commit_changes 호출 시 actually_modified_files 전달
commit_hash = commit_changes(commit_message, project_root, actually_modified_files)
```

```python
# Line 262: Slack 보고서에 actually_modified_files 사용
blocks = build_fix_application_report(
    thread_id=state["thread_id"],
    error_logs=state.get("error_logs", []),
    fix_plan=fix_plan,
    git_branch=branch_name if settings.target_project.git.enabled else None,
    git_commit=commit_hash,
    files_modified=files_modified,
    modified_files=actually_modified_files,  # 실제 수정된 파일만 전달
)
```

---

### 2. Slack 메시지 포맷 개선

#### 문제
1. 에러 메시지 100자 제한으로 잘림
2. 파일 목록 10개 제한 (... 외 N개)
3. Traceback, diff 내용 truncate로 잘림
4. 발생 위치 "unknown:?" 표시

#### 해결
**파일: `/Users/donggyu/error-log_agent/src/slack/message_builder.py`**

##### 2.1 에러 정보 전체 표시

```python
# Line 146-150: 에러 메시지 전체 표시
{"type": "mrkdwn", "text": f"*에러 메시지:*\n{error_info.get('message', 'Unknown')}"},
```

##### 2.2 파일 위치 포맷 개선

```python
# Line 13-30: format_file_location 함수 추가
def format_file_location(error_info: dict) -> str:
    """Format file location for display."""
    file_path = error_info.get('file_path')
    line_number = error_info.get('line_number')

    if file_path and line_number:
        return f"`{file_path}:{line_number}`"
    elif file_path:
        return f"`{file_path}`"
    else:
        return "_위치 정보 없음 (traceback 미포함)_"
```

##### 2.3 파일 목록 전체 표시 (10개 제한 제거)

```python
# Line 907-946: 모든 파일 표시, 긴 경우 자동 블록 분할
if modified_files:
    files_text = "*📁 수정된 파일 목록*\n" + "\n".join(
        f"• `{file}`" for file in modified_files
    )

    # Split into multiple blocks if text is too long
    if len(files_text) > SAFE_TEXT_LENGTH:
        header = "*📁 수정된 파일 목록*\n"
        file_entries = [f"• `{file}`" for file in modified_files]

        current_block = header
        for entry in file_entries:
            if len(current_block) + len(entry) + 1 > SAFE_TEXT_LENGTH:
                blocks.append({
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": current_block}
                })
                current_block = entry + "\n"
            else:
                current_block += entry + "\n"

        if current_block.strip():
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": current_block}
            })
```

##### 2.4 Traceback 전체 표시

```python
# Line 160-198: Traceback 전체 표시, 긴 경우 자동 블록 분할
if traceback_text:
    traceback_header = "*Traceback:*\n```"
    traceback_footer = "```"
    max_traceback_content_length = SAFE_TEXT_LENGTH - len(traceback_header) - len(traceback_footer)

    if len(traceback_text) <= max_traceback_content_length:
        # Fits in one block
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{traceback_header}{traceback_text}{traceback_footer}"
            }
        })
    else:
        # Split into multiple blocks
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{traceback_header}{traceback_text[:max_traceback_content_length]}{traceback_footer}"
            }
        })

        remaining_traceback = traceback_text[max_traceback_content_length:]
        while remaining_traceback:
            chunk = remaining_traceback[:SAFE_TEXT_LENGTH - 6]
            remaining_traceback = remaining_traceback[SAFE_TEXT_LENGTH - 6:]
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"```{chunk}```"
                }
            })
```

##### 2.5 변경 미리보기 전체 표시

```python
# Line 284-323: diff_preview 전체 표시, 없으면 섹션 숨김
if fix_plan.target_files and fix_plan.target_files[0].diff_preview and fix_plan.target_files[0].diff_preview != 'N/A':
    diff_full = fix_plan.target_files[0].diff_preview

    diff_header = "*변경 미리보기:*\n```diff\n"
    diff_footer = "```"
    max_diff_content_length = SAFE_TEXT_LENGTH - len(diff_header) - len(diff_footer)

    if len(diff_full) <= max_diff_content_length:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{diff_header}{diff_full}{diff_footer}"
            }
        })
    else:
        # Split into multiple blocks
        # ... (similar logic)
```

---

### 3. 로그 파싱 문제 분석

#### 문제
- 슬랙 메시지에서 "발생 위치: unknown:?" 표시
- Traceback 미출력
- 변경 미리보기 "N/A" 표시

#### 원인 분석

##### 실제 로그 내용 확인
```bash
tail -100 /Users/donggyu/target-service/logs/app.log
```

**발견된 로그:**
```
2026-03-18 16:04:34,945 - target-service - ERROR - RecursionError: Circular reference detected.
```

- 로그에 **traceback이 포함되지 않음**
- 단순히 에러 메시지만 기록됨
- 파서가 정상 작동하지만 추출할 traceback이 없음

##### 파서 로직 확인
**파일: `/Users/donggyu/error-log_agent/src/log_parser/parser.py`**

```python
# Line 71-102: Traceback 파싱 로직
# Look for traceback after this error line
traceback = None
file_path = None
line_number = None
function_name = None

# Search for traceback in the next 5000 characters
search_window = content[line_start : line_start + 5000]

# Find all tracebacks
tb_matches = list(TRACEBACK_PATTERN.finditer(search_window))

if tb_matches:
    traceback = tb_matches[-1].group(0).strip()

    # Extract file references from traceback
    file_refs = list(FILE_REF_PATTERN.finditer(traceback))
    if file_refs:
        # Prefer target-service files over site-packages
        target_refs = [ref for ref in file_refs if 'target-service' in ref.group(1)]

        if target_refs:
            last_ref = target_refs[-1]
        else:
            last_ref = file_refs[-1]

        file_path = last_ref.group(1)
        line_number = int(last_ref.group(2))
        function_name = last_ref.group(3)
```

**결론**: 파서는 정상 작동하지만, 로그에 traceback이 없으면 file_path와 line_number를 추출할 수 없음

##### 해결 방안
1. `format_file_location()` 함수로 traceback이 없을 때 명확한 메시지 표시
2. diff_preview가 없을 때 섹션 자체를 숨김

```python
# Line 285: diff_preview 조건 강화
if fix_plan.target_files and fix_plan.target_files[0].diff_preview and fix_plan.target_files[0].diff_preview != 'N/A':
```

---

### 4. 에러 로그 생성 방법

#### Target Service 엔드포인트 확인
```bash
# 엔드포인트 확인
grep -r "trigger-error" /Users/donggyu/target-service/src/api/routes.py

# 결과: @router.post("/trigger-error/{error_type}")
```

#### 사용 방법

##### 단일 에러 발생
```bash
curl -X POST http://localhost:8001/trigger-error/zero_division
```

##### 여러 에러 발생
```bash
for error_type in zero_division key_error type_error index_error file_not_found recursion_error; do
  curl -X POST "http://localhost:8001/trigger-error/$error_type" -s > /dev/null
  echo "Triggered: $error_type"
  sleep 1
done
```

#### 사용 가능한 에러 타입
- `zero_division`
- `key_error`
- `type_error`
- `index_error`
- `file_not_found`
- `recursion_error`
- `attribute_error`
- `value_error`
- `connection_refused`

---

## 수정된 파일 목록

### Core Files
1. `/Users/donggyu/error-log_agent/src/agent/nodes/code_fixer.py`
   - `actually_modified_files` 리스트 추가
   - `commit_changes()` 함수에 `modified_files` 파라미터 추가
   - Git 커밋 시 실제 수정된 파일만 staging
   - Slack 보고서에 실제 수정된 파일 전달

2. `/Users/donggyu/error-log_agent/src/slack/message_builder.py`
   - `format_file_location()` 함수 추가
   - 에러 메시지 전체 표시 (100자 제한 제거)
   - 파일 목록 전체 표시 (10개 제한 제거)
   - Traceback 전체 표시 (자동 블록 분할)
   - Diff 전체 표시 (자동 블록 분할)
   - 수정 내용 전체 표시 (자동 블록 분할)
   - diff_preview 없을 때 섹션 숨김

---

## 테스트 결과

### 로그 생성 테스트
```bash
# 실행 시간: 2026-03-23 21:29:11 ~ 21:29:34
for error_type in zero_division key_error type_error index_error file_not_found recursion_error; do
  curl -X POST "http://localhost:8001/trigger-error/$error_type" -s > /dev/null
  echo "Triggered: $error_type"
  sleep 1
done
```

### 생성된 로그
```
2026-03-23 21:29:11,774 - target-service - ERROR - Unexpected error: total_items must be greater than zero.
2026-03-23 21:29:29,170 - target-service - ERROR - Unexpected error: total_items must be greater than zero.
2026-03-23 21:29:32,387 - target-service - ERROR - IndexError: No orders available.
2026-03-23 21:29:33,403 - target-service - ERROR - FileNotFoundError: config/app_settings.json not found.
2026-03-23 21:29:34,421 - target-service - ERROR - RecursionError: Circular reference detected.
```

### 에이전트 동작
- 수집 주기: 1분 간격
- 다음 수집 시간: 21:30:02
- 생성된 에러를 감지하고 분석 시작 예정

---

## 남은 제한 사항

### Traceback이 없는 로그
- 로그에 traceback이 포함되지 않으면 file_path, line_number 추출 불가
- 이 경우 "_위치 정보 없음 (traceback 미포함)_" 메시지 표시
- 소스 코드 기반 분석으로 대응

### 개선 방향
1. Target Service의 로깅 설정 개선하여 traceback 포함
2. LLM에게 diff_preview 생성 요청 강화
3. 로그 형식이 다른 경우 대응할 수 있도록 파서 확장

---

## 참고 사항

### 워크스페이스 구조
```
/Users/donggyu/
├── error-log_agent/          # Main workspace
├── error-log_agent_v2/        # Documentation workspace
└── target-service/            # Test target service
```

### 실행 중인 서비스
- Error Log Agent: http://localhost:8000
- Target Service: http://localhost:8001
