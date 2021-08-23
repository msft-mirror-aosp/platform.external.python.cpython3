#!/bin/bash
set -e

top=$(cd $(dirname $0)/../../../.. && pwd)

out=$top/out/python3
python_src=$top/external/python/cpython3

if [ "$(uname)" == "Darwin" ]; then
    # http://g3doc/devtools/kokoro/g3doc/userdocs/macos/selecting_xcode
    sudo xcode-select -s /Applications/Xcode_12.2.app/Contents/Developer
    export SDKROOT=/Applications/Xcode_12.2.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk
    (cd $python_src; git apply kokoro/0001-Enable-arm64-builds.patch)
fi

rm -fr $out

python3 --version
python3 $python_src/kokoro/build.py $python_src $out $out/artifact "${KOKORO_BUILD_ID:-dev}"
