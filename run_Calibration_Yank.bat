@echo off
echo Starting game...
cd C:\Tasks\Yank-Task
call MRI_Env\Scripts\activate.bat
python Calibration_Yank_Task.py
pause