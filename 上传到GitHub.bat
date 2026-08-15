@echo off
chcp 936 >nul
cd /d "%~dp0"

where git >nul 2>nul
if errorlevel 1 (
    echo [错误] 没有检测到 Git，请先安装 Git。
    echo 下载地址：https://git-scm.com/download/win
    echo 安装完成后，再重新双击本脚本。
    pause
    exit /b 1
)

echo ============================================
echo  上传 emoji-collector 到 GitHub
echo ============================================
echo.
echo 前提：
echo   1. 电脑已安装 Git
echo   2. 已登录 GitHub
echo   3. 先在 GitHub 网页新建一个空仓库，复制它的地址
echo      例如：https://github.com/你的用户名/仓库名.git
echo.
set /p REPO=请输入 GitHub 仓库地址（以 .git 结尾）:

if "%REPO%"=="" (
    echo 未输入地址，取消。
    pause
    exit /b 1
)

echo.
echo 正在初始化并推送...
git init
git config user.name "emoji-collector"
git config user.email "emoji-collector@users.noreply.github.com"
git add .
git commit -m "init emoji collector"
git branch -M main
git remote remove origin 2>nul
git remote add origin "%REPO%"
git push -u origin main

echo.
echo 完成！请打开 GitHub 仓库页面，进入 Actions 手动运行一次。
pause