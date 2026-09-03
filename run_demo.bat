@echo off
cd /d "%~dp0"
python -m app.server --provider demo --video-mode none
