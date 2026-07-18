@echo off
REM AetherOS Voice — dependency installer (Windows, uv)
REM Creates a 3.12 venv and installs mic/STT/speaker-gate deps + Echo Voice runtime.
setlocal
cd /d "%~dp0"
where uv >nul 2>&1 || (echo "uv not found - install from https://astral.sh/uv" && exit /b 1)
uv venv --python 3.12 .venv
call .venv\Scripts\activate.bat
uv pip install numpy scipy sounddevice soundfile torch
uv pip install "faster-whisper" 
REM Echo Voice runtime (from the extracted package)
uv pip install -r "%USERPROFILE%\echo_voice_extract\echo_voice_qwen_integration\pyproject.toml" 2>nul
uv pip install fastapi uvicorn "qwen-tts" soundfile
echo.
echo Install done. Then:
echo   python supervisor.py        (always-on console + steward + voice)
echo   python voice\voice_loop.py --selftest
echo   python voice\voice_loop.py --enroll path\to\your_voice.wav
echo   python voice\voice_loop.py  (live, owner-only)
endlocal
