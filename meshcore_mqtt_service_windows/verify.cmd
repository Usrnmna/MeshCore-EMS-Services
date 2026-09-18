@echo off
setlocal
pushd "%~dp0"
".venv\Scripts\python.exe" -m unittest -v test_service.py test_responder.py test_mqtt_integration.py test_aqi.py test_traffic.py test_rivers.py
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 goto failed
popd
exit /b 0
:failed
popd
exit /b 1
