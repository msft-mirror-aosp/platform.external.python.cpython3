:: Code under repo is checked out to %KOKORO_ARTIFACTS_DIR%\git.
:: The final directory name in this path is determined by the scm name specified
:: in the job configuration

SET OUT=%KOKORO_ARTIFACTS_DIR%\out
SET DEST=%KOKORO_ARTIFACTS_DIR%\dest
SET PYTHON_SRC=%KOKORO_ARTIFACTS_DIR%\git\cpython3

:: Initialize environment variables.
CALL "%VS140COMNTOOLS%\..\..\VC\vcvarsall.bat" amd64
IF %ERRORLEVEL% NEQ 0 goto :end

CALL "%~dp0\build.cmd" "%PYTHON_SRC%" "%OUT%" "%DEST%" "%KOKORO_BUILD_ID%"

:end
exit /b %ERRORLEVEL%
