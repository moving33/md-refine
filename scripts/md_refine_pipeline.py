"""
MD 정제 파이프라인: pdfplumber(표 구조 추출) + ftfy → MD 구조 청킹 → LLM 정제
설정: pipeline_config.json
"""

import json
import re
import sys
import time
import ftfy
import tiktoken
import requests
import pdfplumber
from pathlib import Path
from markitdown import MarkItDown

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SYSTEM_PROMPT = """당신은 한국어 문서 정제 전문가입니다.
입력된 마크다운 텍스트에서 깨진 한글, 어색한 표현, 인코딩 오류를 수정하여
자연스러운 한국어 마크다운으로 반환하세요.

규칙:
1. 마크다운 구조(헤더, 목록, 코드블록, 표)는 반드시 유지
2. 원본의 의미와 내용을 보존하고 과도한 재작성 금지
3. 정제된 텍스트만 반환, 설명이나 주석 추가 금지
4. 이미 올바른 텍스트는 그대로 유지
5. 표(table)의 경우 컬럼 구조를 유지하면서 빈 셀은 그대로 두기"""


# ── 설정 로드 ──────────────────────────────────────────────────────────────────
def load_config(config_path: Path | None = None) -> dict:
    """pipeline_config.json 로드. 파일이 없으면 기본값 반환."""
    defaults = {
        "llm": {
            "base_url": "http://192.168.0.65:8080/v1",
            "model": "bllossom-8b-local",
            "timeout_seconds": 120,
            "temperature": 0.1,
            "max_tokens": 2048,
        },
        "chunking": {
            "max_chunk_tokens": 1800,
            "encoding": "cl100k_base",
        },
        "output": {
            "save_intermediate": True,
            "suffix": "_refined",
            "intermediate_suffix": "_pdfplumber",
        },
    }

    search_paths = []
    if config_path:
        search_paths.append(Path(config_path))
    # 스크립트 위치 → 현재 작업 디렉토리 순서로 탐색
    search_paths += [
        Path(__file__).parent / "pipeline_config.json",
        Path.cwd() / "pipeline_config.json",
    ]

    for p in search_paths:
        if p.exists():
            with open(p, encoding="utf-8") as f:
                user_cfg = json.load(f)
            # 중첩 딕셔너리 병합 (사용자 값이 기본값을 덮어씀)
            for section, values in user_cfg.items():
                if section in defaults and isinstance(values, dict):
                    defaults[section].update(values)
                else:
                    defaults[section] = values
            print(f"      설정 로드: {p}")
            return defaults

    print("      설정 파일 없음 - 기본값 사용")
    return defaults


# ── pdfplumber: 표 → MD 표 ────────────────────────────────────────────────────
def table_to_markdown(data: list) -> str:
    cleaned = []
    for row in data:
        row_cells = []
        for cell in row:
            if cell is None:
                row_cells.append("")
            else:
                row_cells.append(str(cell).replace("\n", " ").replace("|", "｜").strip())
        cleaned.append(row_cells)

    if not cleaned:
        return ""

    col_count = max(len(r) for r in cleaned)
    for row in cleaned:
        while len(row) < col_count:
            row.append("")

    # 전체 행에서 비어있는 열 제거
    non_empty_cols = [
        c for c in range(col_count)
        if any(cleaned[r][c] for r in range(len(cleaned)))
    ]
    if not non_empty_cols:
        return ""
    cleaned = [[row[c] for c in non_empty_cols] for row in cleaned]

    lines = [
        "| " + " | ".join(cleaned[0]) + " |",
        "| " + " | ".join("---" for _ in cleaned[0]) + " |",
    ]
    for row in cleaned[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def extract_pdf_to_md(pdf_path: str) -> str:
    all_parts = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_parts = []

            tables = page.find_tables()
            table_bboxes = []
            for tbl in tables:
                data = tbl.extract()
                if not data:
                    continue
                md_table = table_to_markdown(data)
                if md_table:
                    page_parts.append((tbl.bbox[1], md_table))
                    table_bboxes.append(tbl.bbox)

            words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
            text_lines: dict[float, list] = {}
            for w in words:
                w_top, w_x0 = w["top"], w["x0"]
                in_table = any(
                    b[0] <= w_x0 <= b[2] and b[1] <= w_top <= b[3]
                    for b in table_bboxes
                )
                if not in_table:
                    matched = next((k for k in text_lines if abs(k - w_top) <= 3), None)
                    if matched is None:
                        text_lines[w_top] = []
                        matched = w_top
                    text_lines[matched].append(w["text"])

            if text_lines:
                sorted_tops = sorted(text_lines.keys())
                para_lines: list[str] = []
                prev_top = None
                para_chunks: list[str] = []

                for top in sorted_tops:
                    line_text = " ".join(text_lines[top])
                    if prev_top is not None and (top - prev_top) > 15:
                        para_chunks.append(" ".join(para_lines))
                        para_lines = []
                    para_lines.append(line_text)
                    prev_top = top

                if para_lines:
                    para_chunks.append(" ".join(para_lines))

                first_top = sorted_tops[0]
                for chunk in para_chunks:
                    if chunk.strip():
                        page_parts.append((first_top - 0.1, chunk.strip()))

            page_parts.sort(key=lambda x: x[0])
            all_parts.extend(content for _, content in page_parts)

    return "\n\n".join(all_parts)


# ── ftfy 전처리 ───────────────────────────────────────────────────────────────
def preprocess_with_ftfy(text: str) -> str:
    return ftfy.fix_text(text, normalization="NFC")


# ── MD 구조 청킹 ──────────────────────────────────────────────────────────────
def count_tokens(text: str, enc) -> int:
    return len(enc.encode(text))


def split_by_md_structure(text: str, max_tokens: int, enc) -> list[dict]:
    header_pattern = re.compile(r'^(#{1,6}\s.+)$', re.MULTILINE)
    positions = [m.start() for m in header_pattern.finditer(text)]
    positions.append(len(text))

    if len(positions) <= 1:
        raw_sections = [text]
    else:
        raw_sections = []
        prev = 0
        for pos in positions[:-1]:
            if pos > prev:
                raw_sections.append(text[prev:pos])
            prev = pos
        raw_sections.append(text[positions[-2]:])

    chunks = []
    for section in raw_sections:
        section = section.strip()
        if not section:
            continue
        if count_tokens(section, enc) <= max_tokens:
            chunks.append(section)
        else:
            paragraphs = re.split(r'\n{2,}', section)
            current = ""
            for para in paragraphs:
                candidate = (current + "\n\n" + para).strip() if current else para
                if count_tokens(candidate, enc) <= max_tokens:
                    current = candidate
                else:
                    if current:
                        chunks.append(current)
                    if count_tokens(para, enc) > max_tokens:
                        sub = ""
                        for line in para.split('\n'):
                            trial = (sub + "\n" + line).strip() if sub else line
                            if count_tokens(trial, enc) <= max_tokens:
                                sub = trial
                            else:
                                if sub:
                                    chunks.append(sub)
                                sub = line
                        if sub:
                            chunks.append(sub)
                    else:
                        current = para
            if current:
                chunks.append(current)

    return [{"content": c, "index": i} for i, c in enumerate(chunks)]


# ── LLM 정제 ─────────────────────────────────────────────────────────────────
def refine_chunk_with_llm(chunk_text: str, cfg: dict) -> str:
    llm = cfg["llm"]
    payload = {
        "model": llm["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": chunk_text},
        ],
        "temperature": llm["temperature"],
        "max_tokens": llm["max_tokens"],
        "stream": False,
    }
    try:
        resp = requests.post(
            f"{llm['base_url']}/chat/completions",
            json=payload,
            timeout=llm["timeout_seconds"],
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except requests.exceptions.Timeout:
        print("    [WARN] 타임아웃 - 원본 청크 사용")
        return chunk_text
    except Exception as e:
        print(f"    [WARN] LLM 오류({e}) - 원본 청크 사용")
        return chunk_text


# ── 메인 파이프라인 ────────────────────────────────────────────────────────────
def process_file(input_path: str, output_path: str | None = None, config_path: str | None = None):
    src = Path(input_path)
    if not src.exists():
        print(f"[ERROR] 파일 없음: {input_path}")
        sys.exit(1)

    print("\n설정 로드 중...")
    cfg = load_config(Path(config_path) if config_path else None)

    chunking = cfg["chunking"]
    out_cfg = cfg["output"]
    llm_cfg = cfg["llm"]

    out = Path(output_path) if output_path else src.with_name(src.stem + out_cfg["suffix"] + ".md")
    enc = tiktoken.get_encoding(chunking["encoding"])
    max_chunk = chunking["max_chunk_tokens"]

    print(f"  LLM: {llm_cfg['base_url']}  model={llm_cfg['model']}")
    print(f"  청크: max {max_chunk} tokens  출력: {out.name}")

    # 1단계: 변환
    if src.suffix.lower() == ".pdf":
        print(f"\n[1/4] pdfplumber PDF 추출 중: {src.name}")
        raw_md = extract_pdf_to_md(str(src))
    else:
        print(f"\n[1/4] markitdown 변환 중: {src.name}")
        result = MarkItDown().convert(str(src))
        raw_md = result.text_content
    print(f"      완료 ({count_tokens(raw_md, enc):,} tokens, {len(raw_md):,} chars)")

    # 2단계: ftfy
    print(f"\n[2/4] ftfy 전처리 중...")
    fixed_md = preprocess_with_ftfy(raw_md)
    print(f"      완료 (변경 문자 수: {abs(len(raw_md) - len(fixed_md)):,})")
    if out_cfg["save_intermediate"]:
        inter = src.with_name(src.stem + out_cfg["intermediate_suffix"] + ".md")
        inter.write_text(fixed_md, encoding="utf-8")
        print(f"      중간 결과 저장: {inter.name}")

    # 3단계: 청킹
    print(f"\n[3/4] MD 구조 청킹 중 (max {max_chunk} tokens/chunk)...")
    chunks = split_by_md_structure(fixed_md, max_chunk, enc)
    print(f"      총 {len(chunks)}개 청크 생성")
    for i, ch in enumerate(chunks):
        toks = count_tokens(ch["content"], enc)
        preview = ch["content"][:60].replace('\n', ' ')
        print(f"      청크 {i+1:02d}: {toks:4d} tokens | {preview}...")

    # 4단계: LLM 정제
    print(f"\n[4/4] LLM 정제 중 ({llm_cfg['base_url']})...")
    refined_chunks = []
    total = len(chunks)
    t_total = time.time()
    for ch in chunks:
        toks = count_tokens(ch["content"], enc)
        print(f"      [{ch['index']+1:02d}/{total}] {toks} tokens...", end=" ", flush=True)
        t0 = time.time()
        refined_chunks.append(refine_chunk_with_llm(ch["content"], cfg))
        print(f"완료 ({time.time()-t0:.1f}s)")

    final_md = "\n\n".join(refined_chunks)
    out.write_text(final_md, encoding="utf-8")
    print(f"\n완료! {out}  ({len(final_md):,} chars, {time.time()-t_total:.1f}s)")
    return str(out)


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        process_file(r"C:\dev\working\local-llm-checking-once\RFP.pdf")
    else:
        cfg_arg = next((a.split("=", 1)[1] for a in args if a.startswith("--config=")), None)
        paths = [a for a in args if not a.startswith("--")]
        process_file(paths[0], paths[1] if len(paths) > 1 else None, cfg_arg)
