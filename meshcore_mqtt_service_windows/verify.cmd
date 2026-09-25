@echo off
setlocal
pushd "%~dp0"
".venv\Scripts\python.exe" -m unittest discover -s tests -p "test_*.py" -v
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 goto failed
popd
exit /b 0
:failed
popd
exit /b 1
