@ECHO OFF
REM AetherOS_Hybrid launcher — keeps the console + children alive across sessions.
REM Survives Hermes chat sessions because it runs as a Windows scheduled task (logon trigger),
REM not as a child of the terminal. Restarts supervisor if it dies.
SETLOCAL
SET DIR=C:\Users\nator\AetherOS_Hybrid
SET PY=C:\Users\nator\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe
:loop
TASKLIST /FI "IMAGENAME eq python.exe" | FIND "supervisor.py" >NUL
IF ERRORLEVEL 1 (
  ECHO [%DATE% %TIME%] supervisor not running — starting >> "%DIR%\launcher.log"
  START "" /MIN "%PY%" "%DIR%\supervisor.py"
)
TIMEOUT /T 30 >NUL
GOTO loop
ENDLOCAL
