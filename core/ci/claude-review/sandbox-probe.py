#!/usr/bin/env python3
"""리뷰 Runner의 서비스 sandbox에서 비밀값 없이 실행하는 일회성 검사다.

`/usr/local/lib/<review_name>/`의 root 소유 사본을 probe 서비스가 실행한다. 계정·홈·CLI 경로와 버전,
GitLab 호스트는 서버 설정(`/etc/<review_name>/config.json`)에서 읽는다.
"""
import argparse
import json
import os
from pathlib import Path
try:
    import pwd
except ImportError:  # Windows에서는 제한값 검증만 테스트하며 실제 실행은 Linux 전용이다.
    pwd = None
import re
import socket
import ssl
import subprocess
import tempfile

CONFIG = '/etc/claude-review/config.json'
CLAUDE_API_HOST = 'api.anthropic.com'
CONTROL_SOCKETS = ['/run/docker.sock', '/run/containerd/containerd.sock',
                   '/run/dbus/system_bus_socket', '/run/systemd/private']


def limits_match(values):
    quota, period = values['cpu.max'].split()
    return (quota.isdecimal() and period.isdecimal() and int(period) > 0
            and int(quota) == int(period)
            and values['memory.high'] == str(2 * 1024**3)
            and values['memory.max'] == str(3 * 1024**3)
            and values['memory.swap.max'] == '0'
            and values['pids.max'] == '128')


def cgroup_limits():
    groups = Path('/proc/self/cgroup').read_text().splitlines()
    paths = [line[3:] for line in groups if line.startswith('0::')]
    if len(paths) != 1 or '..' in Path(paths[0]).parts:
        raise ValueError('Expected unified cgroup')
    base = Path('/sys/fs/cgroup') / paths[0].lstrip('/')
    return {key: (base / key).read_text().strip() for key in
            ['cpu.max', 'memory.high', 'memory.max', 'memory.swap.max', 'pids.max']}


def check(name, test):
    try:
        passed = bool(test())
    except Exception as exc:
        print('FAIL:', name, type(exc).__name__, flush=True)
        return False
    print(('PASS: ' if passed else 'FAIL: ') + name, flush=True)
    return passed


def identity(account, home):
    user = pwd.getpwnam(account)
    return (os.getuid() == user.pw_uid != 0 and os.getgid() == user.pw_gid
            and set(os.getgroups()) <= {user.pw_gid} and os.environ.get('HOME') == str(home))


def privileges():
    values = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines()
                  if ':' in line)
    return (values['NoNewPrivs'].strip() == '1'
            and all(int(values[key].strip(), 16) == 0 for key in ['CapEff', 'CapPrm', 'CapBnd']))


def home_writable(home):
    with tempfile.TemporaryFile(dir=home) as output:
        output.write(b'review sandbox probe\n')
    return True


def sockets_blocked():
    for path in CONTROL_SOCKETS:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            try:
                sock.connect(path)
            except OSError:
                continue
            return False
    return True


def claude_version(claude_cli, expected):
    result = subprocess.run([claude_cli, '--version'],
                            capture_output=True, text=True, timeout=30, check=True)
    match = re.fullmatch(r'(\d+\.\d+\.\d+) \(Claude Code\)', result.stdout.strip())
    if not match:
        return False
    print('CLAUDE_VERSION:', match.group(1), flush=True)
    return match.group(1) == expected


def tls(host):
    with socket.create_connection((host, 443), timeout=5) as sock:
        with ssl.create_default_context().wrap_socket(sock, server_hostname=host):
            return True


def load_settings(path):
    server = json.loads(Path(path).read_text(encoding='utf-8'))
    keys = ('account', 'home', 'claude_cli', 'claude_version', 'gitlab_host')
    if not isinstance(server, dict) or not all(isinstance(server.get(key), str) and server[key]
                                               for key in keys):
        raise ValueError('Server configuration fields missing')
    return {key: server[key] for key in keys}


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=CONFIG)
    args = parser.parse_args(arguments)
    try:
        settings = load_settings(args.config)
    except (OSError, ValueError):
        print('SANDBOX_PROBE: FAIL (server configuration unavailable)', flush=True)
        return 1
    account, home = settings['account'], Path(settings['home'])
    checks = [
        ('dedicated account', lambda: identity(account, home)),
        ('no privilege escalation or capabilities', privileges),
        ('cgroup CPU/memory/process limits', lambda: limits_match(cgroup_limits())),
        ('other home directories hidden', lambda: set(os.listdir(home.parent)) == {home.name}),
        ('system filesystem read-only', lambda: os.statvfs('/etc').f_flag & os.ST_RDONLY),
        ('review home writable', lambda: home_writable(home)),
        ('control sockets unavailable (absent or denied)', sockets_blocked),
        ('Claude CLI version without authentication',
         lambda: claude_version(settings['claude_cli'], settings['claude_version'])),
        ('GitLab TLS without authentication', lambda: tls(settings['gitlab_host'])),
        ('Claude API TLS without authentication', lambda: tls(CLAUDE_API_HOST)),
    ]
    results = [check(name, test) for name, test in checks]
    print('SANDBOX_PROBE: ' + ('PASS' if all(results) else 'FAIL'), flush=True)
    return 0 if all(results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
