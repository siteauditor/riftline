@echo off
rem Put the Riot key from backend\.env on the live server and check that Riot
rem takes it. Double-click this file, or run it from cmd or PowerShell.
rem
rem It runs deploy/rotate-key.sh with Git for Windows' own bash, found from
rem where git is installed. A plain "bash" on this machine can be WSL's
rem (C:\Windows\System32\bash.exe), which has neither the ssh settings for
rem MyVPS nor this checkout's paths.

setlocal
cd /d "%~dp0"

set "GITBASH="
for /f "delims=" %%G in ('where git 2^>nul') do (
  if not defined GITBASH if exist "%%~dpG..\bin\bash.exe" set "GITBASH=%%~dpG..\bin\bash.exe"
)
if not defined GITBASH if exist "%ProgramFiles%\Git\bin\bash.exe" set "GITBASH=%ProgramFiles%\Git\bin\bash.exe"
if not defined GITBASH (
  echo rotate-key: Git for Windows was not found. Install it from https://git-scm.com
  set "CODE=1"
  goto done
)

"%GITBASH%" deploy/rotate-key.sh
set "CODE=%ERRORLEVEL%"

:done
echo.
if "%CODE%"=="0" (echo Finished.) else (echo Failed, see the message above.)
rem Keep the window open when it was double-clicked. Windows' own find, by
rem path: where Git's Unix tools come first on PATH, "find" is the Unix one,
rem which took "/c" for a folder and searched all of C:\.
echo %CMDCMDLINE% | "%SystemRoot%\System32\find.exe" /i "/c" >nul && pause
endlocal & exit /b %CODE%
