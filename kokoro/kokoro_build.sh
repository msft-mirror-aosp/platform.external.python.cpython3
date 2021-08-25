#!/bin/bash
set -e

top=$(cd $(dirname $0)/../../../.. && pwd)

out=$top/out/python3
python_src=$top/external/python/cpython3

# On Linux, enter the Docker container and reinvoke this script.
if [ "$(uname)" == "Linux" -a "$SKIP_DOCKER" == "" ]; then
    docker build -t ndk-python3 $python_src/kokoro
    export SKIP_DOCKER=1
    docker run -v$top:$top -eKOKORO_BUILD_ID -eSKIP_DOCKER \
      --entrypoint $python_src/kokoro/kokoro_build.sh \
      ndk-python3
    exit $?
fi

extra_ldflags=
extra_notices=

if [ "$(uname)" == "Darwin" ]; then
    # http://g3doc/devtools/kokoro/g3doc/userdocs/macos/selecting_xcode
    sudo xcode-select -s /Applications/Xcode_12.2.app/Contents/Developer
    export SDKROOT=/Applications/Xcode_12.2.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk
    (cd $python_src; git apply kokoro/0001-Enable-arm64-builds.patch)
elif [ "$(uname)" == "Linux" ]; then
    # Build libffi.a for use with the _ctypes module.
    (cd $top/external/libffi && ./autogen.sh)
    rm -fr $top/out/libffi
    mkdir -p $top/out/libffi/build
    pushd $top/out/libffi/build
    $top/external/libffi/configure \
        --enable-static --disable-shared --with-pic --disable-docs \
        --prefix=$top/out/libffi/install
    make -j$(nproc) install
    popd

    # cpython's configure script will use pkg-config to set LIBFFI_INCLUDEDIR,
    # which setup.py reads. It doesn't use pkg-config to add the library search
    # dir. With no --prefix, libffi.a would install to /usr/local/lib64, which
    # doesn't work because, even though setup.py links using -lffi, setup.py
    # first searches for libffi.{a,so} and needs to find it. setup.py searches
    # in /usr/local/lib and /usr/lib64, but not /usr/local/lib64.
    #
    # Use -Wl,--exclude-libs to hide libffi.a symbols in _ctypes.*.so.
    export PKG_CONFIG_PATH=$top/out/libffi/install/lib/pkgconfig
    extra_ldflags="$extra_ldflags -L$top/out/libffi/install/lib64 -Wl,--exclude-libs=libffi.a"
    extra_notices="$extra_notices $top/external/libffi/LICENSE"
fi

rm -fr $out

python3 --version
python3 $python_src/kokoro/build.py $python_src $out $out/artifact \
    "${KOKORO_BUILD_ID:-dev}" "$extra_ldflags" "$extra_notices"

# Verify that some extensions can be loaded.
$out/install/bin/python3 -c 'import binascii, bz2, ctypes, curses, curses.panel, hashlib, zlib'
