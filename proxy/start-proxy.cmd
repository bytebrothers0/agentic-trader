@echo off
REM Start the OpenCode inference proxy on http://localhost:8080/v1
REM The API key comes from the OPENCODE_API_KEY environment variable
REM (persisted for this user), so no secret lives in this file.
cd /d "%~dp0"
if "%OPENCODE_API_KEY%"=="" (
  echo ERROR: OPENCODE_API_KEY is not set in this shell.
  echo Set it once with:  setx OPENCODE_API_KEY "oc_sk_..."
  exit /b 1
)
opencode-proxy.exe -listen :8080
