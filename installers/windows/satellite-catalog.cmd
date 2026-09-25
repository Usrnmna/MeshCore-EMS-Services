@echo off
setlocal
set PYTHONNOUSERSITE=1
"%~dp0..\..\python\python.exe" "%~dp0..\..\satellite_database\satellite_db.py" --settings "%ProgramData%\MeshCore-EMS\satellite-settings.json" %*
exit /b %errorlevel%
