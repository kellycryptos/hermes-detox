@echo off
title Hermes Agent - Live Demonstration
color 0F
cd /d "%~dp0..\.."

echo ================================================================================
echo Hermes Agent - Live Workflow Session (Hermes Detox Active)
echo ================================================================================
echo.
uv run python docs\demo\demo_workflow.py

echo.
echo ================================================================================
echo Press any key to run the test suite verification (74 tests)...
echo ================================================================================
pause >nul
echo.
uv run python -m unittest discover -s tests -p "test_*.py" -v

echo.
echo ================================================================================
echo Verification Complete. Press any key to exit.
echo ================================================================================
pause >nul
