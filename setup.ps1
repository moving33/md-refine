# md-refine 설치/업데이트 스크립트
# 사용: .\setup.ps1          (최초 설치)
#        .\setup.ps1 --update (git pull 후 skill 파일 갱신)

param([switch]$update)

$ErrorActionPreference = "Stop"
$repoRoot   = $PSScriptRoot
$skillsDir  = "C:\ai-agent-skills"
$claudeCmd  = "$env:USERPROFILE\.claude\commands"
$skillSrc   = "$repoRoot\md-refine.md"
$skillDst   = "$skillsDir\md-refine.md"

Write-Host "`n=== md-refine $(if ($update) {'업데이트'} else {'설치'}) ===" -ForegroundColor Cyan

# ── 1. Python 패키지 설치 ──────────────────────────────────────────────────────
if (-not $update) {
    Write-Host "`n[1/3] Python 패키지 설치 중..."
    $packages = @("pdfplumber", "ftfy", "tiktoken", "markitdown", "requests")
    pip install @packages -q
    if ($LASTEXITCODE -ne 0) { Write-Error "pip install 실패"; exit 1 }
    Write-Host "      완료" -ForegroundColor Green
} else {
    Write-Host "`n[1/3] 패키지 설치 건너뜀 (--update 모드)"
}

# ── 2. ~/.claude/commands → C:\ai-agent-skills junction 확인/생성 ────────────
Write-Host "`n[2/3] Claude Code skill 디렉토리 확인 중..."
if (-not (Test-Path $claudeCmd)) {
    New-Item -ItemType Junction -Path $claudeCmd -Target $skillsDir | Out-Null
    Write-Host "      Junction 생성: $claudeCmd -> $skillsDir" -ForegroundColor Green
} else {
    $item = Get-Item $claudeCmd
    if ($item.LinkType -eq "Junction") {
        Write-Host "      Junction 확인됨: $claudeCmd -> $($item.Target)"
    } else {
        Write-Host "      [WARN] $claudeCmd 가 Junction이 아닙니다. 수동 확인 필요" -ForegroundColor Yellow
    }
}

# ── 3. skill 파일 복사 (원본: repo / 대상: C:\ai-agent-skills\md-refine.md) ──
Write-Host "`n[3/3] skill 파일 등록 중..."
Copy-Item $skillSrc $skillDst -Force
Write-Host "      복사 완료: $skillSrc -> $skillDst" -ForegroundColor Green

# ── 완료 ──────────────────────────────────────────────────────────────────────
Write-Host "`n완료! Claude Code에서 '/md-refine <파일경로>' 로 사용하세요.`n" -ForegroundColor Cyan
Write-Host "설정 파일: $repoRoot\pipeline_config.json"
Write-Host "  → llm.base_url 에 LLM 서버 IP를 입력하세요."
