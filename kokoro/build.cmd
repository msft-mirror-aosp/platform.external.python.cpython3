:: Expected arguments:
:: %1 = python_src
:: %2 = dest_dir

ECHO ON

SET PYTHON_SRC=%1
SET OUT=%2
SET DEST=%3
SET KOKORO_BUILD_ID=%4

cd %PYTHON_SRC%
md %DEST%
IF %ERRORLEVEL% NEQ 0 goto :end

:: Deletes Android.bp or it will be packaged.
DEL Lib\Android.bp
IF %ERRORLEVEL% NEQ 0 goto :end

ECHO ## Building python...
CALL PCbuild\build.bat -c Release -p x64
IF %ERRORLEVEL% NEQ 0 goto :end

ECHO ON
ECHO ## Installing python...
CALL python.bat PC\layout --copy %OUT% --include-dev
IF %ERRORLEVEL% NEQ 0 goto :end

ECHO ON
ECHO ## Installing ucrt...
SET "UCRT_PATH=%WindowsSdkDir%\Redist\%WindowsSDKVersion%\ucrt\DLLs\x64"
IF NOT EXIST "%UCRT_PATH%" (
    SET "UCRT_PATH=%WindowsSdkDir%\Redist\ucrt\DLLs\x64"
)
COPY "%UCRT_PATH%\*" "%OUT%"
IF %ERRORLEVEL% NEQ 0 goto :end

ECHO ## Packaging python...
powershell Compress-Archive -Path "%OUT%\*" -DestinationPath "%DEST%\python3-windows-%KOKORO_BUILD_ID%.zip"
IF %ERRORLEVEL% NEQ 0 goto :end

:: Packages all downloaded externals in externals
ECHO ## Packaging externals...
powershell Compress-Archive -Path ".\externals\*" -DestinationPath "%DEST%\python3-externals-%KOKORO_BUILD_ID%.zip"
IF %ERRORLEVEL% NEQ 0 goto :end

:end
exit /b %ERRORLEVEL%
