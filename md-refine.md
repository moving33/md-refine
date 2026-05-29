PDF 또는 문서 파일을 로컬 LLM으로 정제된 한국어 마크다운으로 변환합니다.

## 사용법
`/md-refine <파일경로> [출력경로] [--config=설정파일경로]`

## 실행 절차

1. `$ARGUMENTS`에서 입력 파일 경로를 파싱한다. 경로가 없으면 현재 디렉토리에서 변환 가능한 파일을 찾아 안내한다.

2. 작업 디렉토리 또는 `C:\ai-agent-skills\md-refine\pipeline_config.json`에서 설정을 로드한다.

3. 다음 명령을 실행한다:
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\ai-agent-skills\md-refine\scripts\md_refine_pipeline.py" <입력파일> [출력파일] [--config=경로]
   ```

4. 실행 완료 후 결과를 요약해서 보고한다:
   - 출력 파일 경로
   - 처리된 청크 수 및 총 소요 시간
   - LLM 연결 정보 (base_url, model)

## 설정 변경

`C:\ai-agent-skills\md-refine\pipeline_config.json` 편집:

```json
{
  "llm": {
    "base_url": "http://<LLM서버IP>:8080/v1",
    "model": "<모델alias명>",
    "timeout_seconds": 120,
    "temperature": 0.1,
    "max_tokens": 2048
  },
  "chunking": {
    "max_chunk_tokens": 1800,
    "encoding": "cl100k_base"
  },
  "output": {
    "save_intermediate": true,
    "suffix": "_refined",
    "intermediate_suffix": "_pdfplumber"
  }
}
```

## 파이프라인 구조

```
입력 파일 (PDF / DOCX / XLSX / PPTX 등)
    ↓ [1단계] pdfplumber (PDF) 또는 markitdown (기타 포맷)
원본 MD 변환
    ↓ [2단계] ftfy 인코딩 자동 수정
전처리 MD → {파일명}_pdfplumber.md 저장
    ↓ [3단계] 헤더/단락 기준 구조적 청킹
N개 청크 (max_chunk_tokens 이하)
    ↓ [4단계] 로컬 LLM 순차 정제
최종 MD → {파일명}_refined.md
```

## 지원 파일 형식
- `.pdf` → pdfplumber (표 구조 보존)
- `.docx` `.pptx` `.xlsx` `.html` `.csv` 등 → markitdown
