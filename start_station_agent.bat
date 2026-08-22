@echo off
setlocal enabledelayedexpansion
title Station Agent

rem Prepni se do korenoveho adresare projektu (adresar tohoto .bat souboru),
rem aby skript fungoval i pri spusteni z jineho pracovniho adresare.
cd /d "%~dp0"

set "URL=http://127.0.0.1:8765"
set "CONFIG_FILE=config.yaml"
set "PYTHON_CMD="

if not exist "%CONFIG_FILE%" (
    echo.
    echo CHYBA: Nenasel jsem soubor "%CONFIG_FILE%" v adresari "%CD%".
    echo Zkontroluj, ze tento .bat soubor je v korenovem adresari projektu
    echo Station Agent a ze existuje config.yaml.
    echo.
    goto :end
)

where python >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=python"
) else (
    where py >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=py -3"
    )
)

if not defined PYTHON_CMD (
    echo.
    echo CHYBA: Python nebyl nalezen v PATH ^(ani "python", ani "py"^).
    echo Nainstaluj Python 3 z https://www.python.org/downloads/windows/
    echo a pri instalaci zaskrtni volbu "Add python.exe to PATH".
    echo.
    echo Pokud mas Python nainstalovany jinde, uprav promennou PYTHON_CMD
    echo v tomto souboru na primou cestu k python.exe.
    echo.
    goto :end
)

echo Pouzivam Python: %PYTHON_CMD%
echo Spoustim Station Agent s konfiguraci "%CONFIG_FILE%"...
echo Az server nabehne, ve vychozim prohlizeci se automaticky otevre %URL%
echo.

rem Otevre prohlizec s kratkym zpozdenim na pozadi, aby HTTP server stihl
rem naskocit driv, nez se na nej prohlizec bude pripojovat.
start "" /min cmd /c "ping -n 5 127.0.0.1 >nul && start %URL%"

%PYTHON_CMD% -m station_agent --config "%CONFIG_FILE%"
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
