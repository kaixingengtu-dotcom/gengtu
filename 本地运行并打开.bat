@echo off
chcp 936 >nul
cd /d "%~dp0"

echo 正在本地采集热门表情包...
python scripts\collect.py --top 30 --keep-days 30
if errorlevel 1 (
    echo 运行出错，请确认已安装 Python。
    pause
    exit /b 1
)

echo.
echo 正在打开表情包网页...
if exist docs\index.html (
    start "" docs\index.html
) else (
    echo 没有找到 docs\index.html，请检查运行输出。
)

pause