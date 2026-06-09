@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
set "MAIN=%ROOT%main.py"
set "LOG=%ROOT%brahma-launch.log"

set "PY_EXE="
set "PY_ARGS="

where pyw.exe >nul 2>&1
if %errorlevel%==0 (
    set "PY_EXE=pyw"
    set "PY_ARGS=-3"
) else (
    if exist "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe" (
        set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
    ) else if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
        set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    ) else (
        where py.exe >nul 2>&1
        if %errorlevel%==0 (
            set "PY_EXE=py"
            set "PY_ARGS=-3"
        ) else (
            if not defined PY_EXE (
                set "PY_EXE=python"
            )
        )
    )
)

> "%LOG%" echo [%date% %time%] Launching Brahma AI - Lite
>> "%LOG%" echo Root: %ROOT%
>> "%LOG%" echo Python: %PY_EXE% %PY_ARGS%

if not exist "%MAIN%" (
    >> "%LOG%" echo [ERROR] main.py not found.
    echo main.py not found in %ROOT%
    pause
    exit /b 1
)

if "%PY_EXE%"=="python" (
    >> "%LOG%" echo [WARN] Falling back to PATH python executable.
)

if defined PY_ARGS (
    "%PY_EXE%" %PY_ARGS% "%MAIN%" >> "%LOG%" 2>&1
) else (
    "%PY_EXE%" "%MAIN%" >> "%LOG%" 2>&1
)

set "EXIT_CODE=%errorlevel%"
if not "%EXIT_CODE%"=="0" (
    >> "%LOG%" echo [ERROR] Launcher exited with code %EXIT_CODE%.
    echo Brahma exited with an error. See brahma-launch.log for details.
    pause
)

endlocal
