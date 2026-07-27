@echo off
REM ====================================================
REM Launch Chrome with remote debugging for Sci-Hub CDP
REM ====================================================
REM After launching, open https://sci-hub.st and solve the captcha
REM Then run: python scripts/scihub_batch.py
REM ====================================================

taskkill /F /IM chrome.exe >nul 2>&1
timeout /t 2 /nobreak >nul

"C:\Program Files\Google\Chrome\Application\chrome.exe" ^
    --remote-debugging-port=9222 ^
    --user-data-dir="C:/temp/chrome_debug" ^
    --no-first-run ^
    --no-default-browser-check ^
    "https://sci-hub.st"

echo.
echo Chrome launched with debug port 9222.
echo 1. Open https://sci-hub.st in this Chrome window
echo 2. Solve the captcha (if any)
echo 3. Run: python scripts/scihub_batch.py
echo.
pause
