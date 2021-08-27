SETLOCAL
SET TOP=%~dp0..\..\..\..
SET PYTHON_SRC=%~dp0..

:: Remove Cygwin from the PATH so we use native tools (e.g. native 7-Zip).
:: (It could leave Cygwin at the very end, but that's less of a problem.)
set PATH=%PATH:C:\cygwin64\bin;=%

call %~dp0build.cmd "%PYTHON_SRC%" "%TOP%\out\python3\artifact"

exit /b %ERRORLEVEL%
