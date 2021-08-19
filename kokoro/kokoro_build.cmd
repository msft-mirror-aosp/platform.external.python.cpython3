SETLOCAL
SET TOP=%~dp0..\..\..\..
SET PYTHON_SRC=%~dp0..

call %~dp0build.cmd "%PYTHON_SRC%" "%TOP%\out\python3\artifact"

exit /b %ERRORLEVEL%
