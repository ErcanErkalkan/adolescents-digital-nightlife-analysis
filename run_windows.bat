@echo off
setlocal
python run_all.py --offline
if errorlevel 1 exit /b %errorlevel%
echo Workflow completed and passed validation.
