#!/usr/bin/env python3

import glob
import multiprocessing
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from typing import Dict, List

PYTHON_SRC = Path(__file__).parent.parent
TOP = PYTHON_SRC.parent.parent.parent

sys.path.append(str(TOP / 'toolchain/ndk-kokoro'))
from build_utils import Host, get_default_host, run_cmd, zip_dir_to_zip, create_new_dir


def build_libffi(host: Host, out_dir: Path) -> (List[str], List[str]):
    """ Build libffi.a for use with the _ctypes module. """
    libffi_src = TOP / 'external/libffi'
    libffi_out = out_dir / 'libffi'
    create_new_dir(libffi_out)

    libffi_out_src = libffi_out / 'src'
    shutil.copytree(libffi_src, libffi_out_src, ignore=shutil.ignore_patterns('.git'))
    run_cmd(['./autogen.sh'], cwd=libffi_out_src)

    build_dir = libffi_out / 'build'
    create_new_dir(build_dir)
    install_dir = libffi_out / 'install'

    configure_path = libffi_out_src / 'configure'
    run_cmd([
        configure_path,
        '--enable-static',
        '--disable-shared',
        '--with-pic',
        '--disable-docs',
        f'--prefix={install_dir}',
        '--disable-multi-os-directory',
    ], cwd=build_dir)

    run_cmd(['make', f'-j{os.cpu_count()}', 'install'], cwd=build_dir)

    # Use -Wl,--exclude-libs to hide libffi.a symbols in _ctypes.*.so.
    configure_args = [
        f'LIBFFI_CFLAGS=-I{install_dir}/include',
        f'LIBFFI_LIBS=-L{install_dir}/lib -lffi -Wl,--exclude-libs=libffi.a',
    ]
    notices = [f'{libffi_src}/LICENSE']

    return configure_args, notices


def build_autoconf_target(host, python_src, build_dir, install_dir,
                          extra_configure_args):
    print('## Building Python ##')
    print('## Build Dir   : {}'.format(build_dir))
    print('## Install Dir : {}'.format(install_dir))
    print('## Python Src  : {}'.format(python_src))
    sys.stdout.flush()

    os.makedirs(build_dir, exist_ok=True)
    os.makedirs(install_dir, exist_ok=True)

    cflags = ['-Wno-unused-command-line-argument']
    ldflags = ['-s']
    config_cmd = [
        os.path.join(python_src, 'configure'),
        '--prefix={}'.format(install_dir),
        '--enable-shared',
        '--with-ensurepip=install',
    ]
    env = dict(os.environ)
    if host == Host.Darwin:
        sdkroot = env.get('SDKROOT')
        if sdkroot:
            print("Using SDK {}".format(sdkroot))
            config_cmd.append('--enable-universalsdk={}'.format(sdkroot))
        else:
            config_cmd.append('--enable-universalsdk')
        config_cmd.append('--with-universal-archs=universal2')

        MAC_MIN_VERSION = '10.14'
        cflags.append('-mmacosx-version-min={}'.format(MAC_MIN_VERSION))
        cflags.append('-DMACOSX_DEPLOYMENT_TARGET={}'.format(MAC_MIN_VERSION))
        cflags.extend(['-arch', 'arm64'])
        cflags.extend(['-arch', 'x86_64'])
        env['MACOSX_DEPLOYMENT_TARGET'] = MAC_MIN_VERSION
        ldflags.append("-Wl,-rpath,'@loader_path/../lib'")

        # Disable functions to support old macOS. See https://bugs.python.org/issue31359
        # Fails the build if any new API is used.
        cflags.append('-Werror=unguarded-availability')
        # Python guards against unavailable sqlite function calls by checking the runtime
        # library version rather than using __builtin_available()
        cflags.append('-Wno-unguarded-availability-new')
        # We're building with a macOS 11+ SDK, so this should be set, but
        # configure doesn't find it because of the unguarded-availability error
        # combined with and older -mmacosx-version-min
        cflags.append('-DHAVE_DYLD_SHARED_CACHE_CONTAINS_PATH=1')
    elif host == Host.Linux:
        # Quoting for -Wl,-rpath,$ORIGIN:
        #  - To link some binaries, make passes -Wl,-rpath,\$ORIGIN to shell.
        #  - To build stdlib extension modules, make invokes:
        #        setup.py LDSHARED='... -Wl,-rpath,\$ORIGIN ...'
        #  - distutils.util.split_quoted then splits LDSHARED into
        #    [... "-Wl,-rpath,$ORIGIN", ...].
        ldflags.append("-Wl,-rpath,\\$$ORIGIN/../lib")

        # Omit DT_NEEDED entries for unused dynamic libraries. This is implicit
        # with Debian's gcc driver but not with CentOS's gcc driver.
        ldflags.append('-Wl,--as-needed')

    config_cmd.append('CFLAGS={}'.format(' '.join(cflags)))
    config_cmd.append('LDFLAGS={}'.format(' '.join(cflags + ldflags)))

    config_cmd += extra_configure_args

    subprocess.check_call(config_cmd, cwd=build_dir, env=env)

    if host == Host.Darwin:
        # By default, LC_ID_DYLIB for libpython will be set to an absolute path.
        # Linker will embed this path to all binaries linking this library.
        # Since configure does not give us a chance to set -install_name, we have
        # to edit the library afterwards.
        libpython = 'libpython3.13.dylib'
        subprocess.check_call(['make',
                               '-j{}'.format(multiprocessing.cpu_count()),
                               libpython],
                              cwd=build_dir)
        subprocess.check_call(['install_name_tool', '-id', '@rpath/' + libpython,
                               libpython], cwd=build_dir)

    subprocess.check_call(['make',
                           '-j{}'.format(multiprocessing.cpu_count()),
                           'install'],
                          cwd=build_dir)
    return (build_dir, install_dir)


def install_licenses(host, install_dir, extra_notices):
    (license_path,) = glob.glob(f'{install_dir}/lib/python*/LICENSE.txt')
    with open(license_path, 'a') as out:
        for notice in extra_notices:
            out.write('\n-------------------------------------------------------------------\n\n')
            with open(notice) as inp:
                out.write(inp.read())


def package_target(host, install_dir, dest_dir, build_id):
    package_name = 'python3-{}-{}.tar.bz2'.format(host.value, build_id)
    package_path = os.path.join(dest_dir, package_name)

    os.makedirs(dest_dir, exist_ok=True)
    print('## Packaging Python ##')
    print('## Package     : {}'.format(package_path))
    print('## Install Dir : {}'.format(install_dir))
    sys.stdout.flush()

    # Libs to exclude, from PC/layout/main.py, get_lib_layout().
    EXCLUDES = [
      "lib/python*/config-*",
      # EXCLUDE_FROM_LIB
      "*.pyc", "__pycache__", "*.pickle",
      # TEST_DIRS_ONLY
      "test", "tests",
      # TCLTK_DIRS_ONLY
      "tkinter", "turtledemo",
      # IDLE_DIRS_ONLY
      "idlelib",
      # TCLTK_FILES_ONLY
      "turtle.py",
      # BDIST_WININST_FILES_ONLY
      "wininst-*", "bdist_wininst.py",
    ]
    tar_cmd = ['tar']
    for pattern in EXCLUDES:
      tar_cmd.append('--exclude')
      tar_cmd.append(pattern)
    tar_cmd.extend(['-cjf', package_path, '.'])
    print(subprocess.list2cmdline(tar_cmd))
    subprocess.check_call(tar_cmd, cwd=install_dir)


def package_logs(out_dir, dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    print('## Packaging Logs ##')
    sys.stdout.flush()
    with tarfile.open(os.path.join(dest_dir, "logs.tar.bz2"), "w:bz2") as tar:
        tar.add(os.path.join(out_dir, 'config.log'), arcname='config.log')


def main(argv):
    python_src = argv[1]
    out_dir = argv[2]
    dest_dir = argv[3]
    build_id = argv[4]
    host = get_default_host()

    build_dir = os.path.join(out_dir, 'build')
    install_dir = os.path.join(out_dir, 'install')

    try:
        configure_args = []
        extra_notices = []
        if host == Host.Linux:
            libffi_configure_args, libffi_notices = build_libffi(host, Path(out_dir))
            configure_args += libffi_configure_args
            extra_notices += libffi_notices

        build_autoconf_target(host, python_src, build_dir, install_dir, configure_args)

        install_licenses(host, install_dir, extra_notices)
        package_target(host, install_dir, dest_dir, build_id)
    except:
        # Keep logs before exit.
        package_logs(build_dir, dest_dir)
        raise


if __name__ == '__main__':
    main(sys.argv)
