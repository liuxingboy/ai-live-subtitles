@echo off
setlocal
cd /d "%~dp0.."
call "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 exit /b 1
if not exist ".local\launcher-build" mkdir ".local\launcher-build"
rc /nologo /fo .local\launcher-build\windows_launcher.res tools\windows_launcher.rc
if errorlevel 1 exit /b 1
cl /nologo /utf-8 /EHsc /MT /O2 tools\windows_launcher.cpp .local\launcher-build\windows_launcher.res /Fo.local\launcher-build\windows_launcher.obj /FeLiveSubtitles.exe /link /SUBSYSTEM:WINDOWS user32.lib
exit /b %errorlevel%
