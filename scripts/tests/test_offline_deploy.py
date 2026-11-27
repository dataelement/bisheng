"""CLI E2E: real archives, checksums, HTTP upload/download and transfer; mocked Docker.

Run: python3 -m unittest discover -s scripts/tests -p test_offline_deploy.py -v
"""
import base64
from collections import Counter
import hashlib
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / 'deploy.sh'
VERSION = '3.1.0-test'
GATEWAY = 'registry.invalid/gateway:from-compose'

DOCKER = r'''#!/usr/bin/env python3
import json, os, pathlib, re, sys
a = sys.argv[1:]
with open(os.environ['DOCKER_LOG'], 'a') as log: log.write(json.dumps(a) + '\n')
def values(path):
    result = {}
    for line in pathlib.Path(path).read_text().splitlines():
        if line and not line.startswith('#') and '=' in line:
            key, val = line.split('=', 1); result[key] = val.strip("'\"")
    return result
if a[0] in ('login', 'pull'):
    if os.environ.get('INSTALL_ONLY'): raise SystemExit('network operation forbidden')
    raise SystemExit(0)
if a[0] == 'compose':
    if a[-1] == 'version': print('Docker Compose fixture'); raise SystemExit(0)
    env = values(a[a.index('--env-file')+1])
    if '--format' in a:
        compose = pathlib.Path(a[a.index('-f')+1]).read_text()
        block = compose.split('\n  gateway:\n',1)[1].split('\n  mysql:',1)[0]
        image = re.search(r'^    image: (.+)$',block,re.M).group(1)
        if image.startswith('${'): image = env['BISHENG_GATEWAY_IMAGE']
        print(json.dumps({'services':{'gateway':{'image':image}}}))
    elif '--images' in a:
        print(env['BISHENG_BACKEND_IMAGE'])
        if 'gateway' in env.get('COMPOSE_PROFILES','').split(','): print(env['BISHENG_GATEWAY_IMAGE'])
    elif 'up' in a:
        assert a[a.index('--pull')+1] == 'never' and '--no-build' in a
    raise SystemExit(0)
if a[0] == 'load': sys.stdin.buffer.read(); raise SystemExit(0)
if a[0] == 'save': pathlib.Path(a[a.index('-o')+1]).write_bytes(b'fixture-image-data'); raise SystemExit(0)
if a[:2] == ['image','inspect']:
    ref = a[-1]
    if '--format' not in a: print('[]'); raise SystemExit(0)
    fmt = a[a.index('--format')+1]
    if 'RepoDigests' in fmt:
        repo = ref.rsplit(':',1)[0]
        print(repo+'@sha256:'+'a'*64)
    else: print('linux/'+('arm64' if os.environ.get('BAD_GATEWAY_ARCH') and 'gateway' in ref else os.environ.get('IMAGE_ARCH', 'amd64')))
    raise SystemExit(0)
raise SystemExit('unexpected docker '+repr(a))
'''

ZSTD = r'''#!/usr/bin/env python3
import pathlib, sys
a = sys.argv[1:]
if '-dc' in a: sys.stdout.buffer.write(pathlib.Path(a[-1]).read_bytes())
else:
    out = a[a.index('-o')+1]
    source = next(x for x in a if not x.startswith('-') and x != out)
    pathlib.Path(out).write_bytes(pathlib.Path(source).read_bytes())
'''


class Store(BaseHTTPRequestHandler):
    def target(self):
        prefix = '/repository/raw-hosted/deploy/bisheng/' + VERSION + '/' + self.server.arch + '/'
        if not self.path.startswith(prefix):
            return None
        return self.server.store / self.path[len(prefix):]

    def authorized(self):
        return self.headers.get('Authorization') == 'Basic ' + base64.b64encode(b'reader:fixture-only').decode()

    def do_GET(self):
        self.server.gets[self.path] += 1
        path = self.target()
        if not self.authorized():
            self.send_error(401)
        elif not path or not path.is_file() or self.path in self.server.block_get:
            self.send_error(404)
        else:
            data = path.read_bytes()
            self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    def do_PUT(self):
        path = self.target()
        self.server.puts.append(self.path)
        if not self.authorized():
            self.send_error(401)
        elif not path or self.path in self.server.block_put:
            self.send_error(409)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.rfile.read(int(self.headers['Content-Length'])))
            self.send_response(201)
            self.end_headers()

    def do_POST(self):
        if not self.authorized():
            self.send_error(401)
            return
        body = self.rfile.read(int(self.headers['Content-Length']))
        headers = ('Content-Type: ' + self.headers['Content-Type'] + '\r\nMIME-Version: 1.0\r\n\r\n').encode()
        message = BytesParser(policy=policy.default).parsebytes(headers + body)
        fields = {part.get_param('name', header='content-disposition'): part.get_payload(decode=True)
                  for part in message.iter_parts()}
        directory = fields['raw.directory'].decode()
        filename = fields['raw.asset1.filename'].decode()
        # Like Nexus, raw.asset filename is a basename and raw.directory selects the folder.
        if '/' in filename:
            self.send_error(400)
            return
        remote = '/repository/raw-hosted/' + directory + '/' + filename
        prefix = '/repository/raw-hosted/deploy/bisheng/' + VERSION + '/' + self.server.arch + '/'
        self.server.puts.append(remote)
        if not remote.startswith(prefix) or remote in self.server.block_put:
            self.send_error(409)
            return
        path = self.server.store / remote[len(prefix):]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fields['raw.asset1'])
        self.send_response(201)
        self.end_headers()

    def log_message(self, *args):
        pass


class OfflineDeployE2E(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='offline-e2e-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        for name, text in [('docker', DOCKER), ('zstd', ZSTD)]:
            file = self.bin / name
            file.write_text(text)
            file.chmod(0o755)
        # Model the Linux deployment host independently of the downloading PC.
        (self.bin / 'sitecustomize.py').write_text("import os,platform\nif os.getenv('INSTALL_ONLY'):\n platform.system=lambda:'Linux'\n platform.machine=lambda:os.getenv('TEST_HOST_ARCH','x86_64')\n")
        self.log = self.root / 'docker.log'
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        PYTHONPATH=str(self.bin), DOCKER_LOG=str(self.log),
                        NEXUS_USER='reader', NEXUS_PASS='fixture-only')
        self.docker = self.root / 'docker'
        shutil.copytree(ROOT / 'docker', self.docker)
        env = self.docker / '.env.example'
        env.write_text(env.read_text().replace('cr.dataelem.com/dataelement/gateway:v1.9.3', GATEWAY))
        self.images = self.root / 'images.txt'
        self.images.write_text('BISHENG_BACKEND_IMAGE backend registry.invalid/backend:v%s\n' % VERSION)
        self.dist = self.root / 'dist'
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Store)
        self.server.store = self.root / 'store'
        self.server.store.mkdir()
        self.server.arch = 'amd64'
        self.server.gets = Counter()
        self.server.puts = []
        self.server.block_get = set()
        self.server.block_put = set()
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = 'http://127.0.0.1:%s' % self.server.server_port
        self.pc = self.root / 'connected pc'

    def execute(self, command, success=True, env=None):
        result = subprocess.run([str(x) for x in command], env=env or self.env, cwd=ROOT,
                                text=True, errors="replace", capture_output=True, timeout=45)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def build(self, split=False, gateway=False, success=True, extra_env=None):
        args = ['bash', ROOT / 'scripts/make-bundle.sh', '--version', VERSION, '--arch', self.server.arch,
                '--images-file', self.images, '--docker-dir', self.docker, '--out', self.dist,
                '--split-size', '10K' if split else '2G']
        if gateway:
            args.append('--with-gateway')
        result = self.execute(args, success=success, env=dict(self.env, **(extra_env or {})))
        if success:
            shutil.copytree(self.dist, self.server.store, dirs_exist_ok=True)
        return result

    def download(self, gateway=False, success=True):
        args = ['bash', DEPLOY, 'download', '--version', VERSION, '--arch', self.server.arch,
                '--base-url', self.url, '--out', self.pc]
        if gateway:
            args.append('--gateway')
        return self.execute(args, success=success)

    def transfer(self):
        isolated = self.root / 'isolated server'
        shutil.copytree(self.pc, isolated)
        # Any attempt to fetch during install must fail immediately.
        (self.bin / 'curl').write_text('#!/bin/sh\necho "NETWORK FORBIDDEN" >&2\nexit 99\n')
        (self.bin / 'curl').chmod(0o755)
        self.log.write_text('')
        return isolated

    def install(self, root, gateway=False, success=True, **env):
        args = ['bash', root / 'deploy.sh', 'install']
        if gateway:
            license = self.root / 'license.txt'
            license.write_text('fixture-license')
            args += ['--gateway', '--license-file', license, '--public-url', 'http://192.0.2.10:3001']
        return self.execute(args, success, dict(self.env, INSTALL_ONLY='1', **env))

    def env_values(self, path):
        return {line.split('=', 1)[0]: line.split('=', 1)[1].strip("'\"")
                for line in path.read_text().splitlines() if line and not line.startswith('#') and '=' in line}

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_full_package_transfer_install_and_retry(self):
        """AC-01/03/04: PC needs no Docker; transferred host performs only offline operations."""
        self.build()
        self.log.write_text('')
        self.download()
        self.assertEqual(self.calls(), [])
        for file in self.pc.rglob('*'):
            if file.is_file():
                self.assertNotIn(b'fixture-only', file.read_bytes())
        isolated = self.transfer()
        self.install(isolated)
        env_path = isolated / ('bisheng-offline-%s-amd64' % VERSION) / 'docker/.env'
        first = env_path.read_bytes()
        self.assertEqual(self.env_values(env_path)['BISHENG_RUNTIME_OFFLINE'], 'true')
        self.assertIn(b'registry.invalid/backend:v' + VERSION.encode(), first)
        self.install(isolated)
        self.assertEqual(env_path.read_bytes(), first)
        self.assertFalse(any(call[0] in ('pull', 'login') for call in self.calls()))
        self.assertTrue(any('up' in call and '--pull' in call for call in self.calls()))

    def test_split_package_download_and_stream_extract(self):
        """AC-02/04: all indexed volumes download and unpack without a merged tar."""
        self.build(split=True)
        self.download()
        self.assertGreater(len(list((self.pc / 'packages').glob('*.part.*'))), 1)
        isolated = self.transfer()
        self.install(isolated)
        self.assertFalse(list((isolated / 'packages').glob('*.tar')))

    def test_arm64_target_selected_independently_of_pc(self):
        """AC-01/04: downloading arm64 on the PC installs on a modeled aarch64 host."""
        self.server.arch = 'arm64'
        self.env['IMAGE_ARCH'] = 'arm64'
        self.build(gateway=True)
        self.download(gateway=True)
        isolated = self.transfer()
        self.install(isolated, gateway=True, TEST_HOST_ARCH='aarch64')
        self.assertTrue((isolated / ('bisheng-offline-%s-arm64' % VERSION) / 'docker/.env').is_file())

    def test_gateway_is_compose_image_and_optional_download(self):
        """AC-05/06: Gateway is pinned by Compose, then loaded from the copied component."""
        self.build(gateway=True)
        self.assertTrue(any(call[0] == 'pull' and call[-1] == GATEWAY for call in self.calls()))
        self.download()
        self.assertFalse((self.pc / 'gateway-addon').exists())
        self.download(gateway=True)
        isolated = self.transfer()
        self.install(isolated, gateway=True)
        env = (isolated / ('bisheng-offline-%s-amd64' % VERSION) / 'docker/.env').read_text()
        self.assertIn("BISHENG_GATEWAY_IMAGE='" + GATEWAY + "'", env)
        calls = self.calls()
        up = [call for call in calls if 'up' in call]
        self.assertEqual(up[0][-1], 'gateway')
        self.assertNotEqual(up[-1][-1], 'gateway')
        self.assertFalse(any(call[0] in ('pull', 'login') for call in calls))

    def test_wrong_gateway_architecture_blocks_publication(self):
        """AC-06: never guess a platform tag suffix or silently use an amd64 Gateway."""
        result = self.build(gateway=True, success=False, extra_env={'BAD_GATEWAY_ARCH': '1'})
        self.assertIn('Gateway 镜像架构', result.stderr)
        self.assertFalse((self.dist / 'download.json').exists())

    def test_gateway_uses_literal_compose_image(self):
        """AC-06: a literal Compose image takes precedence over a different env default."""
        path = self.docker / 'docker-compose.yml'
        actual = 'registry.invalid/gateway:literal-compose-tag'
        path.write_text(path.read_text().replace(
            '${BISHENG_GATEWAY_IMAGE:?run bash docker/install.sh to create docker/.env}', actual))
        self.build(gateway=True)
        index = json.loads((self.dist / 'download.json').read_text())
        self.assertEqual(index['gateway']['image'], actual)
        self.assertTrue(any(call[0] == 'pull' and call[-1] == actual for call in self.calls()))

    def test_corrupt_copy_and_wrong_arch_fail_before_docker(self):
        """AC-07: transfer damage and target architecture mismatch stop before image import."""
        self.build()
        self.download()
        isolated = self.transfer()
        self.install(isolated, success=False, TEST_HOST_ARCH='aarch64')
        self.assertEqual(self.calls(), [])
        next((isolated / 'packages').iterdir()).write_bytes(b'corrupt')
        result = self.install(isolated, success=False)
        self.assertIn('校验失败', result.stderr)
        self.assertEqual(self.calls(), [])

    def test_existing_install_lock_stops_without_touching_services(self):
        """AC-04/07: concurrent installation must not race configuration and identity writes."""
        self.build()
        self.download()
        isolated = self.transfer()
        lock = isolated / '.delivery.lock'
        lock.mkdir()
        result = self.install(isolated, success=False)
        self.assertIn('已有下载/安装任务', result.stderr)
        self.assertTrue(lock.is_dir())
        self.assertEqual(self.calls(), [])

    def test_missing_volume_and_resumable_download(self):
        """AC-02/03/07: a 404 isn't treated as end-of-volumes; retries skip verified files."""
        self.build(split=True)
        index = json.loads((self.dist / 'download.json').read_text())
        archive = [item for item in index['files'] if item['path'].startswith('packages/')]
        blocked = '/repository/raw-hosted/deploy/bisheng/%s/amd64/%s' % (VERSION, archive[-1]['name'])
        self.server.block_get.add(blocked)
        result = self.download(success=False)
        self.assertNotIn('可将整个目录', result.stdout)
        first = '/repository/raw-hosted/deploy/bisheng/%s/amd64/%s' % (VERSION, archive[0]['name'])
        count = self.server.gets[first]
        self.server.block_get.clear()
        self.download()
        self.assertEqual(self.server.gets[first], count)

    def test_unsafe_or_wrong_version_index_is_rejected(self):
        """AC-07: validate version, paths and uniqueness before downloading payload files."""
        self.build()
        original = json.loads((self.dist / 'download.json').read_text())
        for mutation in ('version', 'path', 'duplicate'):
            with self.subTest(mutation=mutation):
                index = json.loads(json.dumps(original))
                if mutation == 'version': index['version'] = '9.9.9'
                elif mutation == 'path': index['files'][0]['path'] = '../escape'
                else: index['files'].append(index['files'][0])
                (self.server.store / 'download.json').write_text(json.dumps(index))
                self.download(success=False)
                self.assertFalse((self.pc / 'deploy.sh').exists())

    def test_download_checksum_failure_is_not_published_locally(self):
        """AC-07: bytes arriving from HTTP must match the published SHA256."""
        self.build()
        package = next(self.server.store.glob('*.tar'))
        package.write_bytes(b'corrupt')
        self.download(success=False)
        self.assertFalse(list((self.pc / 'packages').glob('*.tar')))

    def test_unsafe_tar_member_stops_before_docker(self):
        """AC-07: even a checksummed tar cannot write outside the extracted package."""
        self.build()
        index = json.loads((self.server.store / 'download.json').read_text())
        item = next(item for item in index['files'] if item['path'].startswith('packages/'))
        package = self.server.store / item['name']
        with tarfile.open(package, 'w') as archive:
            entry = tarfile.TarInfo('../escaped')
            entry.size = 1
            archive.addfile(entry, io.BytesIO(b'x'))
        item['sha256'] = hashlib.sha256(package.read_bytes()).hexdigest()
        item['size'] = package.stat().st_size
        (self.server.store / 'download.json').write_text(json.dumps(index))
        self.download()
        isolated = self.transfer()
        self.install(isolated, success=False)
        self.assertEqual(self.calls(), [])
        self.assertFalse((isolated / 'escaped').exists())

    def test_nexus_rest_uploads_gateway_subdirectory(self):
        """AC-08: real multipart requests put Gateway files in the correct raw directory."""
        self.build(gateway=True)
        shutil.rmtree(self.server.store)
        self.server.store.mkdir()
        self.execute(['bash', ROOT / 'scripts/nexus-upload.sh', '--dir', self.dist,
                      '--version', VERSION, '--arch', 'amd64', '--base-url', self.url,
                      '--method', 'rest', '--verify', 'sha256'])
        self.assertTrue((self.server.store / 'gateway-addon/images.tar.zst').is_file())
        self.assertTrue(self.server.puts[-1].endswith('/download.json'))
        self.download(gateway=True)

    def test_index_is_published_after_all_files_only(self):
        """AC-08: failed payload upload must not publish a usable version index."""
        self.build(gateway=True)
        shutil.rmtree(self.server.store)
        self.server.store.mkdir()
        prefix = '/repository/raw-hosted/deploy/bisheng/%s/amd64/' % VERSION
        self.server.block_put.add(prefix + 'gateway-addon/images.tar.zst')
        command = ['bash', ROOT / 'scripts/nexus-upload.sh', '--dir', self.dist,
                   '--version', VERSION, '--arch', 'amd64', '--base-url', self.url,
                   '--method', 'put', '--verify', 'sha256']
        self.execute(command, success=False)
        self.assertFalse((self.server.store / 'download.json').exists())
        self.server.block_put.clear()
        self.execute(command)
        self.assertEqual(self.server.puts[-1], prefix + 'download.json')
        self.download(gateway=True)


if __name__ == '__main__':
    unittest.main()
