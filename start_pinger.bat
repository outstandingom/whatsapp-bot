@echo off
title Render 24/7 Keep-Alive Pinger
echo ======================================================================
echo   Starting Render 24/7 Keep-Alive Pinger...
echo   Target: https://whatapp-51qf.onrender.com/api/health
echo ======================================================================
echo.
py ping_backend.py
pause
