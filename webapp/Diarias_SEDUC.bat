@echo off
title Diarias SEDUC - Sistema Local
cd /d "%~dp0"

echo ============================================================
echo   SISTEMA DE DIARIAS - SEDUC  (versao local)
echo ============================================================
echo.
echo   O navegador abrira automaticamente em alguns segundos.
echo   NAO feche esta janela enquanto estiver usando o sistema.
echo.
echo   Para encerrar: feche o navegador e depois esta janela.
echo ============================================================
echo.

set "STREAMLIT=C:\Users\SEDUC\AppData\Local\Programs\Python\Python311\Scripts\streamlit.exe"

REM abre o navegador apos um pequeno atraso (enquanto o servidor sobe)
start "" /min cmd /c "timeout /t 5 >nul & start http://localhost:8502"

"%STREAMLIT%" run app.py --server.port 8502 --server.headless true

echo.
echo Servidor encerrado. Pode fechar esta janela.
pause
