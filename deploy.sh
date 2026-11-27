#!/usr/bin/env bash
# Standalone entry point: download on a connected PC, install on an isolated host.
set -euo pipefail
command -v python3 >/dev/null 2>&1 || { echo '需要 Python 3' >&2; exit 1; }
# Prompt before the embedded program takes stdin for its source code.
if [[ "${1:-}" == download && " $* " != *" --help "* && " $* " != *" -h "* && -t 0 ]]; then
  if [[ -z "${NEXUS_USER:-}" ]]; then read -r -p 'Nexus 下载账号：' NEXUS_USER; fi
  if [[ -z "${NEXUS_PASS:-}" ]]; then
    read -r -s -p 'Nexus 下载密码：' NEXUS_PASS
    printf '\n' >&2
  fi
  export NEXUS_USER NEXUS_PASS
fi
exec python3 - "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" "$@" <<'PY'
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import quote, urlsplit


def fail(message):
    raise ValueError(message)


@contextmanager
def delivery_lock(root):
    lock = root / '.delivery.lock'
    try:
        lock.mkdir()
    except FileExistsError:
        fail('该目录已有下载/安装任务或遗留锁；确认无任务运行后移除 .delivery.lock 再重试')
    try:
        yield
    finally:
        lock.rmdir()


def run(args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def relative(name):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_./+-]+', name):
        fail('清单包含无效文件路径')
    path = PurePosixPath(name)
    if path.is_absolute() or any(item in ('', '.', '..') for item in name.split('/')):
        fail('清单包含不安全的文件路径')
    return path


def local(root, name):
    relative(name)
    path = root / name
    if path.is_symlink() or root.resolve() not in path.resolve().parents:
        fail('文件路径不能通过符号链接逃逸交付目录')
    return path


def version(value):
    if not isinstance(value, str):
        fail('版本号格式无效')
    value = value[1:] if value.startswith('v') else value
    if not re.fullmatch(r'[0-9][A-Za-z0-9._-]*', value):
        fail('版本号格式无效')
    return value


def load_index(path, expected_version=None, expected_arch=None):
    with path.open(encoding='utf-8') as handle:
        index = json.load(handle)
    if not isinstance(index, dict):
        fail('下载清单必须是对象')
    if index.get('schema_version') != 1 or index.get('product') != 'bisheng':
        fail('不支持的下载清单')
    release = version(index.get('version', ''))
    arch = index.get('arch')
    if arch not in ('amd64', 'arm64') or (expected_arch and arch != expected_arch):
        fail('清单架构与请求不一致')
    if expected_version and release != expected_version:
        fail('清单版本与请求不一致')
    bundle = 'bisheng-offline-%s-%s' % (release, arch)
    if index.get('bundle') != bundle:
        fail('清单包名与版本/架构不一致')
    files = index.get('files')
    if not isinstance(files, list) or not files:
        fail('下载清单没有文件')
    names, paths = set(), set()
    for item in files:
        if not isinstance(item, dict):
            fail('下载清单文件项无效')
        name, path = item.get('name'), item.get('path')
        relative(name)
        relative(path)
        if name in names or path in paths:
            fail('清单文件重复')
        names.add(name)
        paths.add(path)
        if item.get('component') not in ('base', 'gateway'):
            fail('清单组件无效')
        if type(item.get('size')) is not int or item['size'] <= 0:
            fail('清单文件大小无效')
        if not re.fullmatch(r'[a-f0-9]{64}', item.get('sha256', '')):
            fail('清单校验值无效')
        if item['component'] == 'base':
            if path != 'deploy.sh' and not path.startswith('packages/'):
                fail('基础组件文件必须位于 packages/ 或为 deploy.sh')
        elif not path.startswith('gateway-addon/'):
            fail('Gateway 文件必须位于 gateway-addon/')
    script = [item for item in files if item['path'] == 'deploy.sh']
    if len(script) != 1 or script[0]['component'] != 'base':
        fail('清单缺少部署入口')
    archives = sorted(item['path'] for item in files if item['path'].startswith('packages/'))
    full = 'packages/%s.tar' % bundle
    if archives != [full]:
        expected = ['%s.part.%02d' % (full, i) for i in range(len(archives))]
        if not archives or archives != expected:
            fail('清单中的分卷不连续或混有完整包')
    index['archives'] = archives
    return index


def selected(index, gateway):
    if gateway and not any(item['component'] == 'gateway' for item in index['files']):
        fail('该版本未发布 Gateway 离线组件')
    return [item for item in index['files'] if item['component'] == 'base' or gateway]


def matches(path, item):
    return path.is_file() and not path.is_symlink() and path.stat().st_size == item['size'] and sha256(path) == item['sha256']


def curl_config(user, password):
    credentials = user + ':' + password
    if '\n' in credentials or '\r' in credentials:
        fail('下载凭据不能包含换行')
    return 'user = "%s"\n' % credentials.replace('\\', '\\\\').replace('"', '\\"')


def fetch(url, path, config):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.%s.' % path.name, dir=str(path.parent))
    os.close(fd)
    temporary = Path(temporary)
    try:
        # Credentials go through stdin, never argv or files in the delivery directory.
        run(['curl', '--config', '-', '--fail', '--silent', '--show-error', '--location',
             '--connect-timeout', '15', '--retry', '3', '--output', temporary, url],
            input=config, text=True)
        return temporary
    except BaseException:
        temporary.unlink()
        raise


def download(args):
    release = version(args.version)
    base = args.base_url.rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.query or parsed.fragment or parsed.username:
        fail('Nexus 地址无效')
    relative(args.repo)
    root = Path(args.out or ('bisheng-delivery-%s-%s' % (release, args.arch))).resolve()
    root.mkdir(parents=True, exist_ok=True)
    user, password = os.environ.get('NEXUS_USER', ''), os.environ.get('NEXUS_PASS', '')
    if not user or not password:
        fail('请设置 NEXUS_USER / NEXUS_PASS，或在交互终端中执行以输入下载凭据')
    config = curl_config(user, password)
    remote = '%s/repository/%s/deploy/bisheng/%s/%s' % (base, args.repo, release, args.arch)
    index_path = local(root, 'download.json')
    temporary = fetch(remote + '/download.json', index_path, config)
    try:
        index = load_index(temporary, release, args.arch)
        files = selected(index, args.gateway)
        if index_path.exists() and index_path.read_bytes() != temporary.read_bytes():
            fail('同一交付目录已存在不同清单，请使用新的 --out 目录')
        os.replace(str(temporary), str(index_path))
    finally:
        if temporary.exists():
            temporary.unlink()
    for item in files:
        dest = local(root, item['path'])
        if matches(dest, item):
            print('已校验，跳过：' + item['path'], flush=True)
            continue
        print('下载：' + item['path'], flush=True)
        temporary = fetch(remote + '/' + quote(item['name'], safe='/'), dest, config)
        try:
            if not matches(temporary, item):
                fail('文件大小或 SHA256 不一致：' + item['path'])
            os.replace(str(temporary), str(dest))
        finally:
            if temporary.exists():
                temporary.unlink()
    checksum = local(root, 'SHA256SUMS.download')
    checksum.write_text(''.join('%s  %s\n' % (item['sha256'], item['path']) for item in files), encoding='utf-8')
    print('下载校验完成，可将整个目录拷贝到隔离服务器：' + str(root))


class PartsReader:
    def __init__(self, paths):
        self.paths = iter(paths)
        self.handle = None

    def read(self, size):
        chunks = []
        remaining = size
        while remaining:
            if self.handle is None:
                path = next(self.paths, None)
                if path is None:
                    break
                self.handle = path.open('rb')
            chunk = self.handle.read(remaining)
            if not chunk:
                self.handle.close()
                self.handle = None
                continue
            chunks.append(chunk)
            remaining -= len(chunk)
        return b''.join(chunks)

    def close(self):
        if self.handle:
            self.handle.close()


def extract(fileobj, target, top, mode):
    with tarfile.open(fileobj=fileobj, mode=mode) as archive:
        for member in archive:
            name = member.name.rstrip('/')
            path = relative(name)
            if path.parts[0] != top or not (member.isfile() or member.isdir()):
                fail('归档含有越界路径、链接或特殊文件：' + member.name)
            local(target, name)
            archive.extract(member, path=str(target), set_attrs=True)


def verify_manifest(root, release, arch):
    with (root / 'manifest.json').open(encoding='utf-8') as handle:
        manifest = json.load(handle)
    if manifest.get('product') != 'bisheng' or manifest.get('version') != release or manifest.get('arch') != arch:
        fail('包内清单与交付版本/架构不一致')
    for item in manifest.get('files', []):
        if not matches(local(root, item['name']), item):
            fail('包内文件校验失败：' + item['name'])
    files = {item['name'] for item in manifest.get('files', [])}
    archives = files & {'images.tar.zst', 'images.tar.gz', 'images/all-images.tar'}
    if len(archives) != 1 or 'docker.tar.gz' not in files:
        fail('包内缺少镜像或部署归档')
    images = manifest.get('images')
    if not images:
        fail('包内没有镜像清单')
    seen = set()
    for image in images:
        key, ref = image.get('env', ''), image.get('ref', '')
        if not re.fullmatch(r'[A-Z][A-Z0-9_]*_IMAGE', key) or key in seen or not ref or any(c.isspace() for c in ref):
            fail('包内镜像配置无效')
        if image.get('arch') != arch:
            fail('包内镜像架构不一致')
        seen.add(key)
    return manifest, next(iter(archives))


def load_images(path):
    if path.name.endswith('.zst'):
        command = ['zstd', '-dc', path]
    elif path.name.endswith('.gz'):
        command = ['gzip', '-dc', path]
    else:
        command = ['cat', path]
    decompressor = subprocess.Popen([str(arg) for arg in command], stdout=subprocess.PIPE)
    try:
        result = subprocess.run(['docker', 'load'], stdin=decompressor.stdout)
        decompressor.stdout.close()
        code = decompressor.wait()
        if result.returncode or code:
            fail('镜像解压或 docker load 失败')
    finally:
        if decompressor.poll() is None:
            decompressor.kill()
            decompressor.wait()


def set_env(docker_dir, values):
    script = '''set -euo pipefail
SCRIPT_DIR=$1; shift
die() { printf '%s\\n' "$*" >&2; exit 1; }
source "$SCRIPT_DIR/lib/install-env.sh"
while [[ $# -gt 0 ]]; do env_set "$SCRIPT_DIR/.env" "$1" "$2"; shift 2; done
'''
    run(['bash', '-c', script, 'deploy-env', docker_dir] + [part for pair in values for part in pair])


def install(args):
    root = Path(args.dir).resolve()
    index = load_index(root / 'download.json')
    files = selected(index, args.gateway)
    host_arch = {'x86_64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine())
    if platform.system() != 'Linux' or host_arch != index['arch']:
        fail('需要与清单架构匹配的 Linux 部署服务器')
    if args.gateway:
        if not args.license_file or not args.public_url:
            fail('Gateway 需要 --license-file 和 --public-url')
        license_path = Path(args.license_file).resolve()
        if not license_path.is_file() or not license_path.read_text().strip():
            fail('license 文件不存在或为空')
        url = urlsplit(args.public_url)
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment:
            fail('平台地址必须是不带路径的 http(s) origin')
    elif args.license_file or args.public_url:
        fail('license 和平台地址参数需要 --gateway')
    # Verify every selected file before extracting, importing images or touching services.
    for item in files:
        if not matches(local(root, item['path']), item):
            fail('交付文件缺失或校验失败：' + item['path'])
    bundle = local(root, index['bundle'])
    if not bundle.exists():
        with tempfile.TemporaryDirectory(prefix='.unpack-', dir=str(root)) as temporary:
            target = Path(temporary)
            reader = PartsReader([local(root, path) for path in index['archives']])
            try:
                extract(reader, target, index['bundle'], 'r|')
            finally:
                reader.close()
            staged = target / index['bundle']
            verify_manifest(staged, index['version'], index['arch'])
            with (staged / 'docker.tar.gz').open('rb') as handle:
                extract(handle, staged, 'docker', 'r|gz')
            os.replace(str(staged), str(bundle))
    manifest, archive = verify_manifest(bundle, index['version'], index['arch'])
    docker_dir = bundle / 'docker'
    if not (docker_dir / 'install.sh').is_file():
        fail('缺少包内 docker/install.sh')
    gateway = None
    if args.gateway:
        with local(root, 'gateway-addon/manifest.json').open(encoding='utf-8') as handle:
            gateway = json.load(handle)
        if gateway.get('arch') != index['arch'] or gateway.get('image') != index.get('gateway', {}).get('image'):
            fail('Gateway 镜像与交付清单不一致')
    run(['docker', 'compose', 'version'])
    load_images(bundle / archive)
    if gateway:
        load_images(local(root, 'gateway-addon/images.tar.zst'))
    images = list(manifest['images'])
    if gateway:
        images.append({'env': 'BISHENG_GATEWAY_IMAGE', 'ref': gateway['image']})
    for image in images:
        actual = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Os}}/{{.Architecture}}', image['ref']], text=True).strip()
        if actual != 'linux/' + index['arch']:
            fail('本地镜像架构不匹配：' + image['ref'])
    run(['bash', docker_dir / 'install.sh', '--no-gateway', '--no-ft', '--prepare-only'])
    values = [(image['env'], image['ref']) for image in images]
    values += [('BISHENG_RUNTIME_OFFLINE', 'true'), ('BISHENG_RUNTIME_IMAGE_PULL_POLICY', 'never')]
    set_env(docker_dir, values)
    if gateway:
        run(['bash', docker_dir / 'install.sh', '--gateway', '--license-file', license_path,
             '--public-url', args.public_url, '--prepare-only'])
    compose = ['docker', 'compose', '--env-file', docker_dir / '.env', '-f', docker_dir / 'docker-compose.yml']
    run(compose + ['config', '--quiet'])
    refs = subprocess.check_output([str(arg) for arg in compose + ['config', '--images']], text=True).splitlines()
    for ref in sorted(set(refs)):
        run(['docker', 'image', 'inspect', ref], stdout=subprocess.DEVNULL)
    if gateway:
        run(compose + ['up', '-d', '--pull', 'never', '--no-build', 'gateway'])
    run(compose + ['up', '-d', '--pull', 'never', '--no-build'])
    print('已执行离线启动；请检查服务健康、登录和 Gateway 授权结果。部署目录：' + str(docker_dir))


def main():
    parser = argparse.ArgumentParser(prog='deploy.sh', description='BiSheng 离线包：联网电脑下载，隔离服务器安装')
    commands = parser.add_subparsers(dest='command', required=True)
    fetch_parser = commands.add_parser('download', help='下载指定版本全部文件，不需要 Docker')
    fetch_parser.add_argument('--version', required=True)
    fetch_parser.add_argument('--arch', choices=('amd64', 'arm64'), required=True)
    fetch_parser.add_argument('--gateway', action='store_true')
    fetch_parser.add_argument('--out', help='交付目录，默认 bisheng-delivery-<版本>-<架构>')
    fetch_parser.add_argument('--base-url', default=os.environ.get('NEXUS_BASE', 'https://nexus.dataelem.com'))
    fetch_parser.add_argument('--repo', default=os.environ.get('NEXUS_REPO', 'raw-hosted'))
    install_parser = commands.add_parser('install', help='只使用本地文件安装，禁止拉取镜像')
    install_parser.add_argument('--dir', default=sys.argv[1], help='交付目录，默认为 deploy.sh 所在目录')
    install_parser.add_argument('--gateway', action='store_true')
    install_parser.add_argument('--license-file')
    install_parser.add_argument('--public-url')
    args = parser.parse_args(sys.argv[2:])
    if args.command == 'download':
        root = Path(args.out or ('bisheng-delivery-%s-%s' % (version(args.version), args.arch))).resolve()
        root.mkdir(parents=True, exist_ok=True)
    else:
        root = Path(args.dir).resolve()
    with delivery_lock(root):
        if args.command == 'download':
            download(args)
        else:
            install(args)


try:
    main()
except (ValueError, OSError, subprocess.CalledProcessError, tarfile.TarError, KeyError, TypeError) as error:
    print('部署工具停止：%s' % error, file=sys.stderr)
    sys.exit(1)
PY
