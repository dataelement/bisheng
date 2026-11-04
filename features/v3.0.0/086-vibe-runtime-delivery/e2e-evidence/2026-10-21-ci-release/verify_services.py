import json
import os
import secrets
import shlex
import subprocess
import time

ROOT = '/opt/e2e-f086-ci-20261021'
LABEL = 'e2e-f086-ci-20261021'
NETWORK = LABEL
RESULT = '/private/tmp/f086-ci-images-20261021/service-verification.json'
names = []
created_network = False
report = {'release': 'v3.0.0-test-vibe', 'host': '192.168.106.109', 'checks': {}}


def command(*args):
    remote = ' '.join(shlex.quote(value) for value in args)
    return subprocess.check_output(['ssh', '-S', '/private/tmp/f086-ci-image-109.sock', 'root@192.168.106.109', remote]).decode().strip()


def docker(*args):
    return command('docker', *args)


def run(name, image, env, extra=None):
    args = ['run', '-d', '--name', name, '--label', 'bisheng.test=' + LABEL,
            '--network', NETWORK, '--memory', '256m', '--cpus', '0.5']
    for key, value in env.items():
        args += ['-e', key + '=' + value]
    args += extra or []
    args += [image]
    ident = docker(*args)
    names.append(name)
    return ident


def inside(name, code):
    return json.loads(docker('exec', name, 'python', '-c', code))


def wait(name, port):
    deadline = time.time() + 45
    code = ("import json,urllib.request; "
            "r=urllib.request.urlopen('http://127.0.0.1:%s/healthz',timeout=2); "
            "print(json.dumps({'status':r.status,'body':json.load(r)}))") % port
    while time.time() < deadline:
        try:
            return inside(name, code)
        except subprocess.CalledProcessError:
            time.sleep(1)
    raise RuntimeError(name + ' did not become healthy')


try:
    assert not docker('ps', '-a', '--filter', 'label=bisheng.test=' + LABEL, '--format', '{{.ID}}')
    docker('network', 'create', '--internal', '--label', 'bisheng.test=' + LABEL, NETWORK)
    created_network = True
    manager = 'dataelement/bisheng-runtime-manager:v3.0.0-test-vibe-amd64'
    proxy = 'dataelement/bisheng-app-proxy:v3.0.0-test-vibe-amd64'
    report['images'] = {}
    for short, image in [('runtime-manager', manager), ('app-proxy', proxy)]:
        meta = json.loads(docker('image', 'inspect', image))[0]
        report['images'][short] = {'reference': image, 'image_id': meta['Id'],
                                  'architecture': meta['Architecture'],
                                  'user': meta['Config']['User'], 'command': meta['Config']['Cmd']}
        assert meta['Architecture'] == 'amd64'
    engine_name = LABEL + '-engine'
    run(engine_name, 'tecnativa/docker-socket-proxy:0.3.0',
        {'INFO': '1', 'VERSION': '1', 'PING': '1', 'CONTAINERS': '0', 'POST': '0'},
        ['--network-alias', 'engine', '-v', '/var/run/docker.sock:/var/run/docker.sock:ro'])
    manager_name = LABEL + '-manager'
    run(manager_name, manager, {
        'RTM_RECONCILE_ENABLED': 'false', 'RTM_PROTOCOL_VERSION': '2',
        'RTM_NODE_ID': LABEL, 'RTM_DOCKER_HOST': 'tcp://engine:2375',
        'RTM_DATA_ROOT': '/app-data', 'RTM_HOST_DATA_ROOT': ROOT + '/app-data',
        'RTM_INBOUND_KEY_ID': 'ci-inbound', 'RTM_INBOUND_SECRET': secrets.token_hex(32),
        'RTM_PLATFORM_KEY_ID': 'ci-platform', 'RTM_PLATFORM_SECRET': secrets.token_hex(32),
        'RTM_PLATFORM_BASE_URL': 'http://platform-unavailable:7860',
    }, ['--network-alias', 'manager', '--read-only', '--tmpfs', '/tmp:rw,size=32m',
        '-v', ROOT + '/app-data:/app-data'])
    proxy_name = LABEL + '-proxy'
    run(proxy_name, proxy, {
        'APP_PROXY_PROTOCOL_VERSION': '2',
        'APP_PROXY_BACKEND_BASE': 'http://platform-unavailable:7860',
        'APP_PROXY_BACKEND_SECRET': secrets.token_hex(32),
        'APP_PROXY_ROUTE_KEY_ID': 'ci-route', 'APP_PROXY_ROUTE_SECRET': secrets.token_hex(32),
        'APP_PROXY_MANAGER_BASE': 'http://manager:8091',
    }, ['--read-only', '--tmpfs', '/tmp:rw,size=16m'])
    report['checks']['manager_health'] = wait(manager_name, 8091)
    report['checks']['proxy_health'] = wait(proxy_name, 8090)
    checks = inside(proxy_name, '''
import json,urllib.request,urllib.error,os
def status(url):
    request=urllib.request.Request(url,headers={'Accept':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=10) as response:return response.status
    except urllib.error.HTTPError as error:return error.code
result={'uid':os.getuid(),'manager_health':status('http://manager:8091/healthz'),
        'unsigned_control':status('http://manager:8091/v2/runtime/status'),
        'legacy_control':status('http://manager:8091/v1/apps/demo/route'),
        'backend_unavailable_entry':status('http://127.0.0.1:8090/apps/e2e-ci/')}
assert result=={'uid':10001,'manager_health':200,'unsigned_control':403,
                'legacy_control':410,'backend_unavailable_entry':503},result
print(json.dumps(result))
''')
    report['checks']['service_access'] = checks
    engine = inside(manager_name, '''
import json,urllib.request,urllib.error
from runtime_manager.config import get_config
from runtime_manager.docker_backend import _RealDockerBackend
backend=_RealDockerBackend(get_config().docker_host)
info=backend.info()
assert backend.ping()
try:
    urllib.request.urlopen('http://engine:2375/containers/json',timeout=5)
    raise AssertionError('container listing must be denied')
except urllib.error.HTTPError as error:
    assert error.code==403,error.code
print(json.dumps({'engine_id':info['ID'],'ping':True,'container_listing_denied':403}))
''')
    assert engine['engine_id'] == docker('info', '--format', '{{.ID}}')
    report['checks']['engine_via_socket_proxy'] = engine
    for name in [manager_name, proxy_name]:
        meta = json.loads(docker('inspect', name))[0]
        assert not meta['HostConfig']['PortBindings']
        assert not any(item['Destination'] == '/var/run/docker.sock' for item in meta['Mounts'])
        assert meta['HostConfig']['ReadonlyRootfs']
        report['checks'][name] = {'running': meta['State']['Running'], 'host_ports': False,
                                 'docker_socket_mounted': False, 'read_only_rootfs': True}
    report['passed'] = True
finally:
    for name in reversed(names):
        assert docker('inspect', '--format', '{{index .Config.Labels "bisheng.test"}}', name) == LABEL
        docker('rm', '-f', name)
    if created_network:
        docker('network', 'rm', NETWORK)
    report['test_containers_remaining'] = docker('ps', '-a', '--filter', 'label=bisheng.test=' + LABEL, '--format', '{{.ID}}').split()
    with open(RESULT, 'w') as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report, indent=2))
