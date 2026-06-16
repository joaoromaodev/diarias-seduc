@echo off
title Cruzamento de Diarias
echo Iniciando app...
echo Acesse: http://localhost:8502
echo Nao feche esta janela.
echo.
"C:\Users\SEDUC\AppData\Local\Programs\Python\Python311\Scripts\streamlit.exe" run "%~dp0app.py" --server.port 8502
pause
