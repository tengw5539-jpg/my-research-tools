@echo off
REM ============================================================
REM launch_chrome_cdp.cmd — 启动独立 Chrome 调试实例（端口 9222）
REM 不杀现有 Chrome，使用独立 user-data-dir，互不影响
REM ============================================================
REM 启动后：
REM   1. 在打开的 Chrome 窗口访问 https://sci-hub.ru 并手动通过验证码
REM   2. 确认后回到终端，运行: python scripts/scihub_batch.py
REM ============================================================

start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
    --remote-debugging-port=9222 ^
    --user-data-dir="C:/temp/chrome_debug" ^
    --no-first-run ^
    --no-default-browser-check ^
    "https://sci-hub.ru"

timeout /t 5 /nobreak >nul
echo.
echo Chrome 调试实例已启动 (端口 9222)
echo 1. 在 Chrome 窗口打开 https://sci-hub.ru
echo 2. 若出现 DDoS-Guard 验证码，请手动通过
echo 3. 完成后按任意键继续...
pause >nul
