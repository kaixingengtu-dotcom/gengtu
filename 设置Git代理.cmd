@echo off
chcp 936 >nul
cd /d "%~dp0"

echo 当前 Git 代理设置：
echo --------------------------------
git config --global --get http.proxy
git config --global --get https.proxy
echo --------------------------------
echo.
echo 请选择：
echo   1 = 使用代理（推荐，如果你开了 Clash/V2Ray 等）
echo   2 = 不使用代理（直连 GitHub）
echo.
set /p CHOICE=请输入 1 或 2：

if "%CHOICE%"=="1" (
    echo.
    set /p PORT=请输入你的代理端口（例如 7890）:
    if "%PORT%"=="" set PORT=7890
    git config --global http.proxy http://127.0.0.1:%PORT%
    git config --global https.proxy http://127.0.0.1:%PORT%
    echo.
    echo 已设置代理：http://127.0.0.1:%PORT%
) else (
    git config --global --unset-all http.proxy
    git config --global --unset-all https.proxy
    echo.
    echo 已清除 Git 代理设置。
)

echo.
echo 设置完成，可以重新运行上传脚本了。
pause