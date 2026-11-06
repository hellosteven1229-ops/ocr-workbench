@echo off
setlocal
pushd "%~dp0" || exit /b 1
if not defined OCR_BUILD_PYTHON set "OCR_BUILD_PYTHON=%CD%\.venv\Scripts\python.exe"
if not exist "%OCR_BUILD_PYTHON%" (
    echo Create .venv and install requirements-build.txt first. See README.md.
    popd
    exit /b 1
)
"%OCR_BUILD_PYTHON%" -m PyInstaller --noconfirm --clean --onefile --windowed --name OCR-Workbench --manifest "%CD%\app.manifest" --distpath dist --workpath build --specpath build app.py
set "BUILD_EXIT=%ERRORLEVEL%"
popd
exit /b %BUILD_EXIT%
