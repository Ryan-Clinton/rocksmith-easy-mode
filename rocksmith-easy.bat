@echo off
REM Windows command-line launcher. Try the py launcher, fall back to python.
setlocal
where py >nul 2>nul && (py -3 "%~dp0rocksmith-easy" %* & exit /b %errorlevel%)
python "%~dp0rocksmith-easy" %*
