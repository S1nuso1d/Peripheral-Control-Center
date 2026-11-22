@echo off
rem Сборка BatteryTray.exe. Запускать на Windows в папке проекта.
python -m pip install --upgrade -r requirements.txt pyinstaller
python -m PyInstaller --noconsole --onefile --hidden-import diagnose --name BatteryTray battery_tray.py
echo.
echo Готово: dist\BatteryTray.exe
echo Установщик (нужен Inno Setup): iscc installer.iss
pause
