# Copilot Security Review for GitLab

GitLab Merge Request(MR)를 **GitHub Copilot CLI**(`copilot -p`)로 보안 리뷰하고, 결과를 MR **thread(Discussion)** 로 남기는 도구입니다.
[anthropics/claude-code-security-review](https://github.com/anthropics/claude-code-security-review)(MIT)를
GitHub Actions + Claude Code 구조에서 **GitLab CI + Copilot CLI** 구조로 이식한 포크입니다.

## 동작 방식

```
MR 파이프라인 → GitLab API로 MR/diff 조회 → copilot -p 로 보안 감사(JSON)
             → 오탐 필터링(하드 규칙 + copilot 2차 검토) → MR thread 게시
```

| 구성요소 | 역할 |
|---|---|
| `copilot_review/gitlab_client.py` | MR 메타데이터/diff 조회, 인라인 thread 게시(실패 시 일반 thread로 대체), 중복 방지 마커 |
| `copilot_review/copilot_runner.py` | `copilot -p` 비대화형 실행, 프롬프트/결과 파일 교환, 권한 최소화, 재시도 |
| `copilot_review/copilot_filter_client.py` | 오탐 필터링(모든 finding을 copilot 1회 호출로 검토) |
| `copilot_review/findings_filter.py` | 하드 제외 규칙(DoS, rate limit 등) + LLM 필터 결합 |
| `copilot_review/prompts.py` | 보안 감사 프롬프트 |
| `copilot_review/gitlab_mr_audit.py` | 전체 흐름(진입점: `python -m copilot_review.audit`) |
| `templates/security-review.gitlab-ci.yml` | 프로젝트에서 `include`해 쓰는 CI 잡 템플릿 |

## 빠른 시작

### 1. 사전 준비

- 이 저장소를 사내 GitLab에 올립니다(예: `your-group/copliot-security-review`).
- 리뷰 대상 프로젝트의 **CI/CD 변수**(Masked, **Protected 해제** — MR 파이프라인은 보호되지 않은 브랜치에서 실행됩니다)를 등록합니다.

| 변수 | 설명 |
|---|---|
| `COPILOT_GITHUB_TOKEN` | "Copilot Requests" 권한이 있는 fine-grained 토큰. classic(`ghp_`) 토큰은 지원되지 않습니다. 조직의 Copilot CLI 정책도 활성화되어 있어야 합니다. |
| `GITLAB_TOKEN` | `api` 스코프의 Project Access Token. `CI_JOB_TOKEN`은 MR 코멘트를 쓸 수 없습니다. |

- 대상 프로젝트의 job token이 이 도구 저장소를 clone할 수 있어야 합니다(도구 저장소 > Settings > CI/CD > Job token permissions).

### 2. 대상 프로젝트의 `.gitlab-ci.yml`

```yaml
include:
  - project: 'your-group/copliot-security-review'
    ref: main
    file: '/templates/security-review.gitlab-ci.yml'

variables:
  SECURITY_REVIEW_TOOL_REPO: 'your-group/copliot-security-review'

copilot-security-review:
  variables:
    EXCLUDE_DIRECTORIES: 'third_party,vendor,build'
```

Copilot CLI는 Node.js 22 이상이 필요합니다. 폐쇄망이면 `before_script`의 `apt-get`, `npm install`, `git clone`을 사내 미러/사전 빌드 이미지로 바꾸세요.

## 설정(환경변수)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `COPILOT_MODEL` | `claude-sonnet-5.5` | 사용할 모델(`--model`). 조직 정책에서 허용된 모델이어야 합니다. |
| `ENABLE_LLM_FILTERING` | `true` | copilot 2차 오탐 검토 사용 여부 |
| `RUN_EVERY_COMMIT` | `false` | `false`: MR당 1회만 리뷰, `true`: 새 커밋마다 리뷰(이미 올린 finding은 재게시하지 않음) |
| `FAIL_ON_HIGH_SEVERITY` | `false` | HIGH finding이 있으면 잡을 실패 처리(머지 차단은 템플릿의 `allow_failure` 제거 필요) |
| `DRY_RUN` | `false` | 리뷰는 수행하되 MR에 아무것도 게시하지 않음 |
| `POST_CLEAN_SUMMARY` | `true` | finding이 없어도 요약 thread 게시(재실행 방지 마커 역할) |
| `MAX_FINDING_THREADS` | `20` | 게시할 finding thread 최대 개수(초과분은 요약에 목록으로 표시) |
| `EXCLUDE_DIRECTORIES` | 없음 | 쉼표로 구분한 제외 디렉터리 |
| `CUSTOM_SECURITY_SCAN_INSTRUCTIONS` | 임베디드 예시 파일 | 프롬프트에 추가할 점검 항목 파일 경로 |
| `FALSE_POSITIVE_FILTERING_INSTRUCTIONS` | 없음 | 오탐 필터링 규칙 교체 파일 경로 |
| `ALLOW_FORK_MRS` | `false` | fork에서 온 MR 리뷰 허용(기본은 건너뜀) |
| `COPILOT_TIMEOUT` | `20` | copilot 1회 실행 제한(분) |
| `COPILOT_PROMPT_MODE` | `file` | `file`/`stdin`/`arg`. 큰 diff 때문에 기본은 파일 전달 방식 |
| `COPILOT_ALLOW_TOOLS` / `COPILOT_DENY_TOOLS` | 코드 내 기본값 | 쉼표 구분 목록으로 권한 규칙 교체 |
| `COPILOT_EXTRA_ARGS` | 없음 | copilot에 추가로 넘길 옵션(공백 구분) |
| `COPILOT_KEEP_WORKDIR` | `false` | `true`면 `.copilot-review/` 디버그 파일 보존 |

## 임베디드(C/C++, Rust, Java) 대상 참고

- 기본 프롬프트에 메모리 안전성 항목(버퍼 오버플로, UAF, 포맷 스트링, 정수 오버플로, `unsafe`/FFI/JNI)을 추가했습니다.
- `examples/embedded-c-cpp-rust-java-scan-instructions.txt`에 차량 연결 인터페이스(Bluetooth/USB/TCU/진단/OTA) 점검 항목을 담았습니다. 조직 위협 모델에 맞게 수정하세요.
- 하드 제외 규칙의 "C/C++ 파일" 판정에 `.hpp/.cxx/.hh/.hxx`를 추가했고, Rust는 `unsafe`/FFI 관련 finding이면 제외하지 않도록 했습니다.
- **주의:** 원본의 프롬프트와 하드 규칙은 DoS/자원 고갈 finding을 제외합니다. 원격에서 유발 가능한 크래시/메모리 고갈을 보안 이슈로 다루려면 `prompts.py`의 EXCLUSIONS와 `findings_filter.py`의 `_DOS_PATTERNS`를 조정해야 합니다.

## 보안 고려사항

- MR 내용은 신뢰할 수 없는 입력입니다. 프롬프트에 무시 지침을 넣었지만 **프롬프트 인젝션에 대한 완전한 방어는 아닙니다.** 내부 개발자 MR에만 사용하세요(fork MR은 기본 제외).
- copilot 프로세스에는 `GITLAB_TOKEN`, `CI_JOB_TOKEN` 등을 전달하지 않고, URL 접근과 `curl`/`wget`/`git push` 등을 deny 규칙으로 막습니다. 쓰기는 `.copilot-review/` 안으로 제한합니다.
- 모델이 만든 텍스트에 포함된 줄 시작 `/명령`(GitLab quick action)과 `@멘션`은 게시 전에 무력화합니다.
- 코드가 GitHub Copilot 서비스로 전송됩니다. 사내 보안 정책상 허용되는지 확인하세요.

## 로컬 점검

```bash
pip install requests pytest
python -m pytest copilot_review -q

# 실제 MR에 게시하지 않고 리뷰만 실행
export CI_API_V4_URL=https://gitlab.example.com/api/v4 CI_PROJECT_ID=123 CI_MERGE_REQUEST_IID=45
export GITLAB_TOKEN=... COPILOT_GITHUB_TOKEN=... DRY_RUN=true
cd /path/to/target/checkout && PYTHONPATH=/path/to/this/repo python -m copilot_review.audit
```

## 원본 대비 변경점

- GitHub Actions(`action.yml`, `.github/`, `scripts/comment-pr-findings.js`) 제거 → GitLab CI 템플릿과 Python 게시 로직으로 대체
- Claude Code CLI + Anthropic API 호출 제거 → Copilot CLI 호출로 통일(오탐 필터링도 Copilot CLI 1회 호출)
- GitHub 캐시 기반 "이미 실행함" 표시 → MR thread 안의 HTML 주석 마커로 대체
- `evals/`(Claude Code 기반 평가 도구)와 `.claude/commands/security-review.md` 제거

## 알려진 한계 / 확인 필요

- 권한 규칙 패턴(`shell(git diff:*)`, `write(.copilot-review/*)`, `url`)은 문서의 형식을 따랐지만, 여러 단어 명령 패턴의 정확한 동작은 사용하는 CLI 버전에서 확인하세요. 어긋나면 `COPILOT_ALLOW_TOOLS`/`COPILOT_DENY_TOOLS`로 조정합니다.
- 결과는 stdout 파싱에 의존하지 않도록 "결과 파일 우선, stdout 보조" 방식입니다. CLI의 JSON 출력 모드는 사용하지 않습니다.
- "프롬프트 너무 김" 오류 문자열은 문서화되어 있지 않아 키워드 추정으로 감지합니다.
- GitLab `/merge_requests/:iid/diffs` 엔드포인트가 없는 구버전은 `/changes`로 대체합니다. 인라인 thread가 거부되면 일반 thread로 대체합니다.

라이선스: MIT (원본 저작권 고지는 `LICENSE`에 유지)
