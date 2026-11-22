@echo off
rem Build PeripheralControlCenter.exe. Run from the project directory on Windows.
python -m pip install --upgrade -r requirements.txt pyinstaller
python -m PyInstaller --noconsole --onefile --name PeripheralControlCenter battery_tray.py
echo.
echo Done: dist\PeripheralControlCenter.exe
echo Installer (requires Inno Setup 6): iscc installer.iss
pause
