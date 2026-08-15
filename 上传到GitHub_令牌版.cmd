@echo off
chcp 936 >nul
cd /d "%~dp0"

where git >nul 2>nul
if errorlevel 1 (
    echo [错误] 没有检测到 Git，请先安装 Git。
    pause
    exit /b 1
)

echo ============================================
echo  上传到 GitHub（令牌版，不用在黑窗口粘贴）
echo ============================================
echo.
set /p REPO=请输入 GitHub 仓库地址（例如 https://github.com/你的用户名/仓库名.git）:
if "%REPO%"=="" (
    echo 未输入地址，取消。
    pause
    exit /b 1
)

set /p GHUSER=请输入你的 GitHub 用户名（例如 kaixingengtu-dotcom）:
if "%GHUSER%"=="" (
    echo 未输入用户名，取消。
    pause
    exit /b 1
)

echo.
echo 请输入 Personal Access Token（输入时屏幕不会显示，输入完直接回车）：
set /p TOKEN=
if "%TOKEN%"=="" (
    echo 未输入令牌，取消。
    pause
    exit /b 1
)

rem 从仓库地址里取出 用户名/仓库名.git 部分
set REPO_PATH=%REPO:https://github.com/=%

echo.
echo 正在初始化并推送...
git init
if errorlevel 1 goto :fail

git config user.name "emoji-collector"
git config user.email "emoji-collector@users.noreply.github.com"

git add .
git commit -m "init emoji collector"
if errorlevel 1 goto :fail

git branch -M main
git remote remove origin 2>nul
git remote add origin "https://%GHUSER%:%TOKEN%@github.com/%REPO_PATH%"

echo 正在推送到 GitHub，请稍等...
git push -u origin main
set RESULT=%ERRORLEVEL%

rem 推送完成后，把远程地址里的令牌去掉，避免令牌存在本地配置里
git remote set-url origin "https://github.com/%REPO_PATH%"

if not "%RESULT%"=="0" goto :fail

echo.
echo 完成！请打开 GitHub 仓库页面，进入 Actions 手动运行一次。
pause
exit /b 0

:fail
echo.
echo [失败] 上传没有成功，请检查：
echo   1. 用户名是否正确
echo   2. 令牌是否完整复制（ghp_ 开头）
echo   3. 令牌是否勾选了 repo 和 workflow 权限
echo   4. 网络是否能连接 GitHub
pause
exit /b 1