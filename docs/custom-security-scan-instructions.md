# 사용자 정의 보안 점검 항목

`CUSTOM_SECURITY_SCAN_INSTRUCTIONS` 환경변수에 텍스트 파일 경로를 지정하면, 기본 점검 항목(Data Exposure) 뒤에 파일 내용이 프롬프트로 추가됩니다.
기본 항목은 그대로 유지되며, 동일한 HIGH/MEDIUM/LOW 기준이 적용됩니다.

## 형식

```
**카테고리 이름:**
- 점검할 구체적인 취약점 또는 패턴
- 또 다른 점검 항목

**다른 카테고리:**
- ...
```

## 예시

- 임베디드 / 차량(AVN, 텔레매틱스): [`examples/embedded-c-cpp-rust-java-scan-instructions.txt`](../examples/embedded-c-cpp-rust-java-scan-instructions.txt) (CI 템플릿의 기본값)
- 산업별 예시(원본 제공): [`examples/custom-security-scan-instructions.txt`](../examples/custom-security-scan-instructions.txt)

## 작성 팁

- 항목은 구체적으로, 코드에서 확인 가능한 패턴 위주로 작성합니다.
- 조직의 위협 모델(공격자가 접근 가능한 인터페이스)을 명시하면 오탐이 줄어듭니다.
- 기본 프롬프트의 EXCLUSIONS(DoS, 자원 고갈 등)와 충돌하는 항목은 `prompts.py`를 함께 조정해야 합니다.
