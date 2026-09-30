#!/bin/sh
# Build /opt/code-root from the Python already installed in this image.
# Runs once, as root, inside `docker build`. Code-node executions never run it.
set -eu

exec python - <<'PY'
import os
import shutil
import stat
import subprocess
import sys

ROOT = "/opt/code-root"
JAIL_PYTHON = "/usr/bin/python"
JAIL_PATH = "/usr/bin:/bin"
TEST_ID = 65534
MODULES = (
    "json", "math", "re", "datetime", "time", "random", "collections",
    "itertools", "functools", "decimal", "base64", "hashlib", "resource", "ast",
)
SKIP_DIRS = {
    "site-packages", "dist-packages", "test", "idlelib", "tkinter",
    "turtledemo", "ensurepip",
}

seen = set()


def fail(message):
    sys.stderr.write("build-code-root: %s\n" % message)
    sys.exit(1)


def under_app(path):
    return path == "/app" or path.startswith("/app/")


def base_executable():
    names = ("python%d.%d" % sys.version_info[:2], "python3", "python")
    candidates = []
    if sys.prefix != sys.base_prefix:
        home = ""
        with open(os.path.join(sys.prefix, "pyvenv.cfg")) as fh:
            for line in fh:
                key, _, value = line.partition("=")
                if key.strip() == "home":
                    home = value.strip()
        if home:
            candidates.extend(os.path.join(home, name) for name in names)
    candidates.append(getattr(sys, "_base_executable", "") or "")
    candidates.append(sys.executable)
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            real = os.path.realpath(candidate)
            if not under_app(real):
                return real
    fail("no base interpreter outside /app")


def place(path):
    """Mirror a host path into ROOT, recreating every symlink along it.

    Destinations are always built from fully resolved parents, so nothing is
    ever written through a symlink that points back out of ROOT.
    """
    path = os.path.normpath(path)
    if path == "/" or path in seen:
        return
    seen.add(path)
    parent = os.path.dirname(path)
    place(parent)
    host = os.path.join(os.path.realpath(parent), os.path.basename(path))
    dest = ROOT + host
    if os.path.islink(host):
        target = os.readlink(host)
        if not os.path.lexists(dest):
            os.symlink(target, dest)
        if not os.path.isabs(target):
            target = os.path.join(os.path.dirname(host), target)
        place(target)
    elif os.path.isdir(host):
        os.makedirs(dest, exist_ok=True)
    elif os.path.isfile(host):
        if not os.path.lexists(dest):
            shutil.copy2(host, dest)
    elif os.path.lexists(host):
        fail("unsupported file type: %s" % host)


def skipped(name):
    return name in SKIP_DIRS or name.startswith("config-")


def walk(top):
    for dirpath, dirnames, filenames in os.walk(top):
        dirnames[:] = [d for d in dirnames if not skipped(d)]
        for name in dirnames + filenames:
            yield os.path.join(dirpath, name)


def place_tree(top):
    place(top)
    for path in walk(os.path.realpath(top)):
        place(path)


def shared_libs(binary):
    result = subprocess.run(
        ["ldd", binary], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        universal_newlines=True,
    )
    for line in result.stdout.splitlines():
        parts = line.split()
        if "=>" in parts:
            index = parts.index("=>")
            if index + 1 < len(parts) and parts[index + 1].startswith("/"):
                yield parts[index + 1]
        elif parts and parts[0].startswith("/"):
            yield parts[0]


def install_ld_cache(directories):
    """Make copied libraries visible inside the jail without LD_LIBRARY_PATH.

    The host linker finds libpython via /etc/ld.so.cache (often /usr/local/lib).
    That cache is not part of the jail, and /usr/bin/python is a symlink, so
    $ORIGIN/../lib points at /usr/lib and misses the real library. A cache built
    from the directories we actually copied is consulted by the jailed linker.
    """
    if not directories:
        return
    etc = os.path.join(ROOT, "etc")
    os.makedirs(etc, exist_ok=True)
    with open(os.path.join(etc, "ld.so.conf"), "w") as fh:
        for directory in sorted(directories):
            fh.write(directory + "\n")
    ldconfig = shutil.which("ldconfig")
    if not ldconfig:
        fail("ldconfig not found")
    result = subprocess.run(
        [ldconfig, "-r", ROOT],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
    )
    if result.returncode != 0:
        fail("ldconfig failed: %s" % result.stderr[-2000:])
    if not os.path.isfile(os.path.join(etc, "ld.so.cache")):
        fail("ldconfig did not write /etc/ld.so.cache")


def normalize_permissions():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        for path in [dirpath] + [os.path.join(dirpath, n) for n in dirnames + filenames]:
            info = os.lstat(path)
            os.lchown(path, 0, 0)
            if stat.S_ISLNK(info.st_mode):
                continue
            if stat.S_ISDIR(info.st_mode):
                os.chmod(path, 0o555)
                continue
            if info.st_mode & (stat.S_ISUID | stat.S_ISGID):
                fail("setuid or setgid file in jail: %s" % path)
            os.chmod(path, 0o555 if info.st_mode & 0o111 else 0o444)


def make_devices():
    dev = os.path.join(ROOT, "dev")
    os.makedirs(dev, exist_ok=True)
    for name, minor in (("null", 3), ("urandom", 9)):
        node = os.path.join(dev, name)
        os.mknod(node, stat.S_IFCHR | 0o666, os.makedev(1, minor))
        os.chown(node, 0, 0)
        os.chmod(node, 0o666)
    os.chmod(dev, 0o555)


SELF_TEST = r'''
import json, os, sys, time
for name in sys.argv[1].split(","):
    __import__(name)
assert (os.getuid(), os.getgid()) == (%(id)d, %(id)d), (os.getuid(), os.getgid())
assert os.getgroups() == [%(id)d], os.getgroups()
with open("/dev/null", "w") as fh:
    fh.write("x")
with open("/dev/urandom", "rb") as fh:
    assert len(fh.read(8)) == 8
for probe in ("/bisheng-write-probe", "%(python_dir)s/bisheng-write-probe"):
    try:
        open(probe, "w")
    except OSError:
        pass
    else:
        raise SystemExit("jail is writable: " + probe)
time.localtime()
sys.stdout.write(json.dumps({"ok": True}))
''' % {"id": TEST_ID, "python_dir": os.path.dirname(JAIL_PYTHON)}


def self_test():
    chroot = shutil.which("chroot")
    if not chroot:
        fail("chroot command not found")
    env = {"PATH": JAIL_PATH, "LANG": "C.UTF-8"}
    if os.environ.get("TZ"):
        env["TZ"] = os.environ["TZ"]
    command = [
        chroot, "--userspec=%d:%d" % (TEST_ID, TEST_ID), "--groups=%d" % TEST_ID,
        ROOT, JAIL_PYTHON, "-I", "-S", "-B", "-X", "utf8",
        "-c", SELF_TEST, ",".join(MODULES),
    ]
    result = subprocess.run(
        command, env=env, cwd="/", stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
    )
    if result.returncode != 0 or result.stdout.strip() != '{"ok": true}':
        fail("self-test failed (exit %d): %s" % (result.returncode, result.stderr[-4000:]))


def main():
    if os.geteuid() != 0:
        fail("must run as root")

    exe = base_executable()
    stdlib = os.path.realpath(os.path.dirname(os.__file__))
    if under_app(stdlib):
        fail("stdlib is under /app: %s" % stdlib)

    if os.path.lexists(ROOT):
        shutil.rmtree(ROOT)
    os.makedirs(ROOT)

    place(exe)
    place_tree(stdlib)
    lib_dirs = set()
    for binary in [exe] + [p for p in walk(stdlib) if p.endswith(".so")]:
        for lib in shared_libs(binary):
            place(lib)
            lib_dirs.add(os.path.dirname(os.path.realpath(lib)))
    install_ld_cache(lib_dirs)

    if os.path.isdir("/usr/share/zoneinfo"):
        place_tree("/usr/share/zoneinfo")
    if os.path.lexists("/etc/localtime"):
        place("/etc/localtime")

    place(os.path.dirname(JAIL_PYTHON))
    if exe != JAIL_PYTHON:
        link = ROOT + os.path.join(
            os.path.realpath(os.path.dirname(JAIL_PYTHON)), os.path.basename(JAIL_PYTHON)
        )
        if os.path.lexists(link):
            fail("%s already exists in jail and is not the base interpreter" % JAIL_PYTHON)
        os.symlink(exe, link)

    normalize_permissions()
    make_devices()
    self_test()
    sys.stdout.write("build-code-root: %s ready (python %s)\n" % (ROOT, exe))


main()
PY
