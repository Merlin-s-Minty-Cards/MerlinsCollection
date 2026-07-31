@echo off
REM Run tests and write results to test-results.txt
REM Usage: run-tests.cmd [all|backend|frontend|mcp]
REM Output: test-results.txt in repo root

setlocal enabledelayedexpansion

set "ROOT=c:\Users\ethar\.cursor\projects\MerlinsCollection-Secondary"
set "OUT=%ROOT%\test-results.txt"
set "SUITE=%~1"
if "%SUITE%"=="" set "SUITE=all"

echo [test-runner] Starting %SUITE% tests at %date% %time% > "%OUT%"
echo [test-runner] Status: RUNNING >> "%OUT%"
echo. >> "%OUT%"

if "%SUITE%"=="backend" goto :backend
if "%SUITE%"=="frontend" goto :frontend
if "%SUITE%"=="mcp" goto :mcp
if "%SUITE%"=="all" goto :all

echo [test-runner] Unknown suite: %SUITE% >> "%OUT%"
echo [test-runner] Status: ERROR >> "%OUT%"
goto :eof

:all
call :backend
echo. >> "%OUT%"
echo ============================================ >> "%OUT%"
echo. >> "%OUT%"
call :frontend
echo. >> "%OUT%"
echo ============================================ >> "%OUT%"
echo. >> "%OUT%"
call :mcp
goto :done

:backend
echo [backend] Running pytest... >> "%OUT%"
cd /d "%ROOT%"
python -m pytest backend/tests -q --tb=short >> "%OUT%" 2>&1
echo [backend] Exit code: %errorlevel% >> "%OUT%"
goto :eof

:frontend
echo [frontend] Running vitest... >> "%OUT%"
cd /d "%ROOT%\frontend"
call npx vitest run --reporter=verbose >> "%OUT%" 2>&1
echo [frontend] Exit code: %errorlevel% >> "%OUT%"
goto :eof

:mcp
echo [mcp-server] Running vitest... >> "%OUT%"
cd /d "%ROOT%\mcp-server"
call npx vitest run --reporter=verbose >> "%OUT%" 2>&1
echo [mcp-server] Exit code: %errorlevel% >> "%OUT%"
goto :eof

:done
echo. >> "%OUT%"
echo ============================================ >> "%OUT%"
echo [test-runner] Completed at %date% %time% >> "%OUT%"
echo [test-runner] Status: DONE >> "%OUT%"
