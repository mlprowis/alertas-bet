@echo off
REM Script para obtener el MEJOR PARTIDO EN VIVO desde Railway
REM Ejecutar: GET_MEJOR_PARTIDO.bat

setlocal enabledelayedexpansion

echo.
echo ========================================
echo  ^🏆 OBTENIENDO MEJOR PARTIDO EN VIVO
echo ========================================
echo.

REM Intentar primero con la URL estándar
set "RAILWAY_URL=https://alertas-bet-production.up.railway.app"

echo Esperando a que Railway esté listo...
timeout /t 5 /nobreak

echo.
echo Buscando mejor partido ahora...
echo.

REM Hacer request con curl
curl -s "%RAILWAY_URL%/webhook/best-match" > temp_response.json

REM Verificar si el archivo tiene contenido
for %%A in (temp_response.json) do set "size=%%~zA"
if "%size%"=="0" (
    echo ❌ Error: No se recibió respuesta de Railway
    echo.
    echo Posibles causas:
    echo   1. Railway aún está deployando (espera 5-10 minutos)
    echo   2. URL incorrecta
    echo.
    echo Acción: Ve a https://railway.app ^-^> alertas-bet ^-^> Deployments
    echo         Copia la URL correcta
    goto :end
)

echo ✅ RESPUESTA RECIBIDA:
echo.
type temp_response.json

echo.
echo.
echo Si status = "ok", revisa tu Telegram - la alerta ya fue enviada
echo.
echo ========================================

:end
del temp_response.json 2>nul
pause
