@echo off
rem agrck shim for cmd/PowerShell on Windows (Git Bash uses bin/agrck)
if defined AGRCK_PYTHON (set "_PY=%AGRCK_PYTHON%") else (set "_PY=python")
"%_PY%" "%~dp0..\pipeline\agrck.py" %*
