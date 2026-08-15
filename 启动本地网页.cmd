@echo off
chcp 936 >nul
cd /d "%~dp0"

echo 正在启动 DeepSeek 表情雷达本地服务器...
echo 网页地址：http://localhost:8765
echo 老梗搜索：http://localhost:8765/search.html
echo 关闭本窗口即可停止服务。
echo.

start "" /b cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8765/"
python server.py
pause