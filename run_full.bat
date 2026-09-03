@echo off
cd /d "%~dp0"
python -m app.server --provider lmstudio --video-mode fasth3
