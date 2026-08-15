@echo off
chcp 936 >nul
cd /d "%~dp0"

where git >nul 2>nul
if errorlevel 1 (
    echo [错误] 没有检测到 Git，请先安装 Git。
    echo 下载地址：https://git-scm.com/download/win
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
if errorlevel 1 goto :fail

git config user.name "emoji-collector"
git config user.email "emoji-collector@users.noreply.github.com"

git add .
git commit -m "init emoji collector" >nul 2>&1
echo 已检查本地提交（没有新改动也会继续推送）。

git branch -M main
git remote remove origin 2>nul
git remote add origin "%REPO%"

echo.
echo 正在推送到 GitHub，请稍等...
git push -u origin main
if errorlevel 1 goto :fail

echo.
echo 完成！请打开 GitHub 仓库页面，进入 Actions 手动运行一次。
pause
exit /b 0

:fail
echo.
echo [失败] 上传没有成功，请仔细看上面的红色错误信息。
echo.
echo 常见原因：
echo   1. 令牌 Token 没有勾选 workflow 权限（必须勾选 repo 和 workflow）
echo   2. 令牌 Token 已过期或复制少了字符
echo   3. 网络无法连接 GitHub
echo.
echo 如果错误里提到 workflow，请重新生成 Token：
echo   https://github.com/settings/tokens
echo   生成时一定要勾选：repo 和 workflow
pause
exit /b 1