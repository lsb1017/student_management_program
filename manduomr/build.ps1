param([string]$Python = '..\.venv\Scripts\python.exe')
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    & $Python -m PyInstaller --noconfirm --clean --distpath dist --workpath build ManduAcademy.spec
    if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
    & ".\dist\학원성적관리\학원성적관리.exe" --smoke-test ".\dist\smoke.json"
    if ($LASTEXITCODE -ne 0) { throw 'Smoke test failed. See dist\smoke.json.' }
} finally { Pop-Location }
