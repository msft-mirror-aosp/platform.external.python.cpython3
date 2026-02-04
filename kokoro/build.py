#!/usr/bin/env python3

import fileinput
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
from build_utils import Host, get_default_host, run_cmd, zip_dir_to_zip, create_new_dir, LinuxArm64Musl


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

    env = os.environ.copy()
    if host == Host.LinuxArm64:
        env['CC'] = LinuxArm64Musl.CC
        env['CXX'] = LinuxArm64Musl.CXX
        env['CFLAGS'] = LinuxArm64Musl.CFLAGS
        env['LDFLAGS'] = LinuxArm64Musl.LDFLAGS
        env['LD_LIBRARY_PATH'] = LinuxArm64Musl.LD_LIBRARY_PATH

    configure_path = libffi_out_src / 'configure'
    run_cmd([
        configure_path,
        '--enable-static',
        '--disable-shared',
        '--with-pic',
        '--disable-docs',
        f'--prefix={install_dir}',
        '--disable-multi-os-directory',
    ], cwd=build_dir, env=env)

    run_cmd(['make', f'-j{os.cpu_count()}', 'install'], cwd=build_dir)

    # Use -Wl,--exclude-libs to hide libffi.a symbols in _ctypes.*.so.
    configure_args = [
        f'LIBFFI_CFLAGS=-I{install_dir}/include',
        f'LIBFFI_LIBS=-L{install_dir}/lib -lffi -Wl,--exclude-libs=libffi.a',
    ]
    notices = [f'{libffi_src}/LICENSE']

    return configure_args, notices


def modify_line_in_file(file: Path, prefix: str, replace: str = None, append: str = None):
    for line in fileinput.input(str(file), inplace=True):
        line = line.rstrip('\r\n')
        if line.startswith(prefix):
            if replace:
                line = replace + '\n'
            if append:
                line += append
        print(line)


def build_bzip2(host: Host, out_dir: Path) -> (List[str], List[str]):
    """ Build libbz2.a for use with the _bz2 module. """
    bzip2_src = TOP / 'external/bzip2'
    bzip2_out = out_dir / 'bzip2'
    create_new_dir(bzip2_out)

    bzip2_out_src = bzip2_out / 'src'
    shutil.copytree(bzip2_src, bzip2_out_src, ignore=shutil.ignore_patterns('.git'))

    # bzip2 has no configure script, the compiler and flags are hardcoded at the
    # top of Makefile.
    makefile = bzip2_out_src / 'Makefile'
    modify_line_in_file(makefile, 'CC=', replace=f'CC={LinuxArm64Musl.CC}')
    modify_line_in_file(makefile, 'AR=', replace=f'AR={LinuxArm64Musl.AR}')
    modify_line_in_file(makefile, 'RANLIB=', replace=f'RANLIB={LinuxArm64Musl.RANLIB}')
    modify_line_in_file(makefile, 'LDFLAGS=', append=f' {LinuxArm64Musl.LDFLAGS}')
    modify_line_in_file(makefile, 'CFLAGS=', append=f' {LinuxArm64Musl.CFLAGS}')

    install_dir = bzip2_out / 'install'
    run_cmd(['make', f'-j{os.cpu_count()}', 'install', f'PREFIX={install_dir}'], cwd=bzip2_out_src)

    configure_args = [
        f'BZIP2_CFLAGS=-I{install_dir}/include',
        f'BZIP2_LIBS=-L{install_dir}/lib -lbz2 -Wl,--exclude-libs=libbz2.a',
    ]
    notices = [f'{bzip2_src}/LICENSE']

    return configure_args, notices


def build_ncurses(host: Host, out_dir: Path) -> (List[str], List[str]):
    """ Build libncursesw.a for use with the _curses module. """
    ncurses_src = TOP / 'external/ncurses'
    ncurses_out = out_dir / 'ncurses'
    create_new_dir(ncurses_out)

    ncurses_out_src = ncurses_out / 'src'
    shutil.copytree(ncurses_src, ncurses_out_src, ignore=shutil.ignore_patterns('.git'))

    install_dir = ncurses_out / 'install'

    env = os.environ.copy()
    if host == Host.LinuxArm64:
        env['CC'] = LinuxArm64Musl.CC
        env['CXX'] = LinuxArm64Musl.CXX
        env['CFLAGS'] = LinuxArm64Musl.CFLAGS + ' -fPIC'
        env['LDFLAGS'] = LinuxArm64Musl.LDFLAGS
        env['LD_LIBRARY_PATH'] = LinuxArm64Musl.LD_LIBRARY_PATH

    run_cmd([
        f'{ncurses_src}/configure',
        f'--prefix={install_dir}',
        '--enable-widec',
        '--without-cxx-binding',
    ], cwd=ncurses_out_src, env=env)

    run_cmd(['make', f'-j{os.cpu_count()}'], cwd=ncurses_out_src, env=env)
    run_cmd(['make', 'install.libs', 'install.includes'], cwd=ncurses_out_src, env=env)

    configure_args = [
        f'CURSES_CFLAGS=-I{install_dir}/include -I{install_dir}/include/ncursesw',
        f'CURSES_LIBS=-L{install_dir}/lib -lncursesw -Wl,--exclude-libs=libncursesw.a',
    ]
    notices = [f'{ncurses_src}/LICENSE']

    return configure_args, notices


def build_autoconf_target(host: Host, python_src: Path, build_dir: Path, install_dir: Path,
                          extra_configure_args: List[str]):
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
    elif host == Host.LinuxArm64:
        ldflags.append("-Wl,-rpath,\\$$ORIGIN/../lib")
        ldflags.append('-Wl,--as-needed')
        cflags.append(LinuxArm64Musl.CFLAGS)
        ldflags.append(LinuxArm64Musl.LDFLAGS)

        config_cmd.append(f'CC={LinuxArm64Musl.CC}')
        config_cmd.append(f'CXX={LinuxArm64Musl.CXX}')
        # Everything must come from the sysroot or be compiled locally against
        # musl, so disable PKG_CONFIG
        config_cmd.append(f'PKG_CONFIG=/bin/false')
        env['LD_LIBRARY_PATH'] = f'{LinuxArm64Musl.SYSROOT}/lib'

    config_cmd.append('CFLAGS={}'.format(' '.join(cflags)))
    config_cmd.append('LDFLAGS={}'.format(' '.join(cflags + ldflags)))

    config_cmd += extra_configure_args

    subprocess.check_call(config_cmd, cwd=build_dir, env=env)

    # The python build rules may call python to regenerate some of the source
    # files, make sure it uses an up-to-date python.
    python_prebuilt = TOP / 'prebuilts/python' / host.value / 'bin/python3'
    env['PYTHON_FOR_REGEN'] = str(python_prebuilt)

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
                               libpython], cwd=build_dir, env=env)

    subprocess.check_call(['make',
                           '-j{}'.format(multiprocessing.cpu_count()),
                           'install'],
                          cwd=build_dir, env=env)
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



def copy_extra_libs(host, install_dir) -> List[Path]:
    if host == Host.LinuxArm64:
        os.makedirs(install_dir + '/lib', exist_ok=True)
        shutil.copy(LinuxArm64Musl.LIBC_MUSL, install_dir + '/lib/libc_musl.so')
        return LinuxArm64Musl.LIBC_MUSL_NOTICES
    return []


def main(argv):
    python_src = Path(argv[1])
    out_dir = Path(argv[2])
    dest_dir = Path(argv[3])
    build_id = argv[4]
    host = get_default_host()

    build_dir = out_dir / 'build'
    install_dir = out_dir / 'install'
    src_out_dir = out_dir / 'src'

    try:
        configure_args = []
        extra_notices = []
        if host == Host.Linux or host == Host.LinuxArm64:
            libffi_configure_args, libffi_notices = build_libffi(host, Path(out_dir))
            configure_args += libffi_configure_args
            extra_notices += libffi_notices

        if host == Host.LinuxArm64:
            # Building for Linux arm64 uses a musl sysroot that is incompatible
            # with any libraries installed on the host, compile bzip2 and ncurses
            # dependencies first.
            bzip2_configure_args, bzip2_notices = build_bzip2(host, Path(out_dir))
            configure_args += bzip2_configure_args
            extra_notices += bzip2_notices

            ncurses_configure_args, ncurses_notices = build_ncurses(host, Path(out_dir))
            configure_args += ncurses_configure_args
            extra_notices += ncurses_notices

        # The python build sometimes writes to the source tree, make a copy of
        # the sources to use during the build.
        if src_out_dir.exists():
            shutil.rmtree(src_out_dir)
        shutil.copytree(python_src, src_out_dir, ignore=shutil.ignore_patterns('.git'))

        build_autoconf_target(host, src_out_dir, build_dir, install_dir, configure_args)

        extra_notices += copy_extra_libs(host, install_dir)

        install_licenses(host, install_dir, extra_notices)
        package_target(host, install_dir, dest_dir, build_id)
    except:
        # Keep logs before exit.
        package_logs(build_dir, dest_dir)
        raise


if __name__ == '__main__':
    main(sys.argv)
