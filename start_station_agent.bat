@echo off
setlocal enabledelayedexpansion
title Station Agent

rem Prepni se do korenoveho adresare projektu (adresar tohoto .bat souboru),
rem aby skript fungoval i pri spusteni z jineho pracovniho adresare.
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

set "URL=http://127.0.0.1:8765"
set "CONFIG_FILE=%PROJECT_DIR%config.yaml"
set "PYTHON_EXE=%PROJECT_DIR%.venv\Scripts\python.exe"

if not exist "%CONFIG_FILE%" (
    echo.
    echo CHYBA: Nenasel jsem soubor "%CONFIG_FILE%".
    echo Zkontroluj, ze tento .bat soubor je v korenovem adresari projektu
    echo Station Agent a ze existuje config.yaml.
    echo.
    goto :end
)

if exist "%PYTHON_EXE%" goto :python_ready

rem V tomto checkoutu neni .venv: over skutecny interpreter pres py launcher.
set "PYTHON_EXE="
for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
if defined PYTHON_EXE if exist "%PYTHON_EXE%" goto :python_ready

rem Posledni fallback: obecny python je pouzit jen pokud vrati platnou cestu.
set "PYTHON_EXE="
for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
if defined PYTHON_EXE if exist "%PYTHON_EXE%" goto :python_ready

set "PYTHON_EXE="
if not defined PYTHON_EXE (
    echo.
    echo CHYBA: Nebyl nalezen overeny Python interpreter.
    echo Ocekavana cesta: "%PROJECT_DIR%.venv\Scripts\python.exe"
    echo nebo funkcni instalace dostupna pres py -3 / python.
    echo.
    goto :end
)

:python_ready
if not defined PYTHON_EXE (
    echo.
    echo CHYBA: Python interpreter nebyl nalezen.
    echo Nainstaluj Python 3 z https://www.python.org/downloads/windows/
    echo a pri instalaci zaskrtni volbu "Add python.exe to PATH".
    echo.
    echo Pokud mas Python nainstalovany jinde, vytvor .venv v projektu.
    echo.
    goto :end
)

echo Pouzivam Python: "%PYTHON_EXE%"
echo Spoustim Station Agent s konfiguraci "%CONFIG_FILE%"...
echo Az server nabehne, ve vychozim prohlizeci se automaticky otevre %URL%
echo.

rem Otevre prohlizec s kratkym zpozdenim na pozadi, aby HTTP server stihl
rem naskocit driv, nez se na nej prohlizec bude pripojovat.
start "" /min cmd /c "ping -n 5 127.0.0.1 >nul && start %URL%"

"%PYTHON_EXE%" -m station_agent --config "%CONFIG_FILE%"
set "EXITCODE=%errorlevel%"

echo.
if not "%EXITCODE%"=="0" (
    echo Station Agent skoncil s chybou ^(navratovy kod %EXITCODE%^).
    echo Viz vypis chyby vyse.
) else (
    echo Station Agent byl ukoncen.
)

:end
echo.
echo Okno zustava otevrene, aby bylo videt pripadnou chybu. Zavri ho rucne
echo nebo stiskni libovolnou klavesu pro ukonceni.
pause >nul
endlocal
