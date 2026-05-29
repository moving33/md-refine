# md-refine

PDF·문서 파일을 로컬 LLM으로 정제된 한국어 마크다운으로 변환하는 Claude Code skill.

## 라이선스

### 이 프로젝트 코드
**MIT License** — 자유롭게 사용·수정·배포 가능.  
자세한 내용은 [LICENSE](LICENSE) 파일 참조.

### 주요 의존 라이브러리

| 라이브러리 | 라이선스 | 용도 |
|-----------|---------|------|
| [markitdown](https://github.com/microsoft/markitdown) | MIT (Microsoft) | PDF 외 문서 → MD 변환 |
| [pdfplumber](https://github.com/jsvine/pdfplumber) | MIT | PDF 표 구조 파싱 |
| [ftfy](https://github.com/rspeer/python-ftfy) | MIT | 유니코드/인코딩 자동 수정 |
| [tiktoken](https://github.com/openai/tiktoken) | MIT (OpenAI) | 토큰 수 계산 |

### 사용 모델: Llama-3-Korean-Bllossom-8B
이 프로젝트는 기본 예시 모델로 **Bllossom** (Llama 3 기반 한국어 특화 모델)을 사용합니다.

- **모델**: [Bllossom/llama-3-Korean-Bllossom-8B](https://huggingface.co/MLP-KTLim/llama-3-Korean-Bllossom-8B)
- **기반 모델**: Meta Llama 3 8B
- **라이선스**: [Meta Llama 3 Community License](https://llama.meta.com/llama3/license/)
  - 월간 활성 사용자 7억 명 미만 서비스에서 상업적 사용 허용
  - 타 LLM 학습·개선 목적 사용 금지
  - 배포 시 라이선스 및 사용 정책 포함 필수
  - 자세한 제한 사항은 Meta 공식 라이선스 문서 확인

> **주의**: 상업적 사용 또는 대규모 서비스 적용 전 반드시 Meta Llama 3 Community License 전문을 검토하세요.

---

## 아키텍처

```
입력 파일 (PDF / DOCX / XLSX 등)
  → [1단계] pdfplumber (PDF) / markitdown (기타)
  → [2단계] ftfy 인코딩 자동 수정
  → [3단계] 헤더·단락 기준 구조적 청킹
  → [4단계] 로컬 LLM 순차 정제
  → {파일명}_refined.md 출력
```

---

## 사전 요구사항

### 1. Python 3.11 이상

```powershell
# 설치 확인
python --version

# 미설치 시
winget install Python.Python.3.13
```

### 2. Claude Code CLI

```powershell
npm install -g @anthropic-ai/claude-code
```

### 3. 로컬 LLM 서버 (llama.cpp + Bllossom 모델)

#### 모델 파일 다운로드

HuggingFace CLI 또는 브라우저에서 직접 다운로드:

```bash
# HuggingFace CLI 사용 시
pip install huggingface_hub
huggingface-cli download Bllossom/llama-3-Korean-Bllossom-8B-Q4_K_M-GGUF \
  llama-3-Korean-Bllossom-8B-Q4_K_M.gguf \
  --local-dir ./models/llama-3-Korean-Bllossom-8b
```

#### Docker Compose로 서버 실행

NVIDIA GPU가 있는 Linux/Windows 서버에서:

```yaml
# docker-compose.yml
services:
  bllossom8b:
    image: ghcr.io/ggml-org/llama.cpp:server-cuda
    container_name: bllossom-8b
    runtime: nvidia
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
      - NVIDIA_DRIVER_CAPABILITIES=compute,utility
    ports:
      - "8080:8080"
    volumes:
      - ./models/llama-3-Korean-Bllossom-8b:/models:ro
    command:
      [
        "-m", "/models/llama-3-Korean-Bllossom-8B-Q4_K_M.gguf",
        "-ngl", "999",        # GPU 레이어 수 (999 = 전체 GPU 오프로드)
        "-c", "8192",         # 컨텍스트 윈도우
        "--parallel", "1",    # 동시 요청 수
        "--flash-attn", "on",
        "--host", "0.0.0.0",
        "--port", "8080",
        "--alias", "bllossom-8b-local",
        "--jinja",
        "--cache-type-k", "q8_0",
        "--cache-type-v", "q8_0"
      ]
```

```bash
# 서버 시작
docker compose up -d

# 연결 확인 (모델 목록 응답이 오면 정상)
curl http://<서버IP>:8080/v1/models
```

> **GPU 없는 환경**: `image`를 `ghcr.io/ggml-org/llama.cpp:server`로 변경하고  
> `-ngl 0` 으로 설정 (CPU 전용, 속도 느림)

---

## 설치

```powershell
# 1. 클론
git clone <repo-url> C:\ai-agent-skills\md-refine

# 2. 셋업 (Python 패키지 설치 + Claude Code skill 등록)
cd C:\ai-agent-skills\md-refine
.\setup.ps1
```

---

## 설정

`pipeline_config.json`에서 LLM 연결 정보 수정:

```json
{
  "llm": {
    "base_url": "http://<LLM서버IP>:8080/v1",
    "model": "bllossom-8b-local",
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

| 항목 | 설명 | 변경 시점 |
|------|------|---------|
| `llm.base_url` | LLM 서버 주소 | 서버 IP/포트 변경 시 |
| `llm.model` | 모델 alias명 | 모델 교체 시 |
| `llm.timeout_seconds` | 요청 타임아웃(초) | 대용량 파일 처리 시 |
| `llm.temperature` | 생성 온도 (0=결정론적) | 정제 강도 조절 시 |
| `chunking.max_chunk_tokens` | 청크 최대 토큰 | 모델 컨텍스트 변경 시 |
| `output.save_intermediate` | 중간 결과 저장 여부 | 디버깅 시 |

---

## 사용

Claude Code에서:
```
/md-refine 파일경로.pdf
/md-refine 파일경로.xlsx 출력경로.md
```

직접 실행:
```powershell
$env:PYTHONIOENCODING="utf-8"
python scripts\md_refine_pipeline.py 파일경로.pdf
python scripts\md_refine_pipeline.py 파일경로.pdf --config=pipeline_config.json
```

---

## 업데이트

```powershell
cd C:\ai-agent-skills\md-refine
git pull
.\setup.ps1 --update
```
