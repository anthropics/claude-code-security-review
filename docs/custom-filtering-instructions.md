# 사용자 정의 오탐 필터링 규칙

`FALSE_POSITIVE_FILTERING_INSTRUCTIONS` 환경변수에 텍스트 파일 경로를 지정하면, copilot 2차 검토 프롬프트의
기본 규칙(`copilot_review/copilot_filter_client.py`의 `DEFAULT_FILTERING_INSTRUCTIONS`)이 **파일 내용으로 교체**됩니다.

## 구조

기본 규칙과 같은 구성을 권장합니다.

```
HARD EXCLUSIONS - Automatically exclude findings matching these patterns:
1. ...

SIGNAL QUALITY CRITERIA - For remaining findings, assess:
1. ...

PRECEDENTS -
1. ...
```

## 예시

[`examples/custom-false-positive-filtering.txt`](../examples/custom-false-positive-filtering.txt) (원본 제공 예시, 조직 환경에 맞게 수정 필요)

## 참고

- 하드 제외 규칙(`findings_filter.py`의 정규식)은 이 파일과 별개로 먼저 적용됩니다.
- `ENABLE_LLM_FILTERING=false`이면 하드 규칙만 적용됩니다.
- 모든 finding은 copilot 1회 호출로 함께 검토되며, 호출이 실패하면 finding을 모두 유지합니다.
