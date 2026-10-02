#!/usr/bin/env python3
"""Claude 리뷰 계정 UID에만 거는 nftables 보호 규칙이며 다른 Runner와 UFW 규칙은 변경하지 않는다.

root가 `/usr/local/lib/<review_name>/`의 root 소유 사본으로 실행한다. 서버 설정은
`/etc/<review_name>/config.json`이며 리뷰 스크립트(review_common.py)와 같은 키를 쓴다.
"""
import argparse
import copy
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

MARKER = 'harness claude review guard v1'
CONFIG = '/etc/claude-review/config.json'
NFT = '/usr/sbin/nft'
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}
# review_common.SERVER_KEYS와 같아야 한다(테스트가 비교한다). root 실행 경로를 줄이려고 공통 모듈을 읽지 않는다.
SERVER_KEYS = {'claude_cli', 'claude_version', 'workdir', 'account', 'uid', 'home', 'nft_table',
               'deny_ips', 'dns_ips', 'gitlab_host'}
TABLE_PATTERN = re.compile(r'^[a-z][a-z0-9_]{0,31}$')
ACCOUNT_PATTERN = re.compile(r'^[a-z_][a-z0-9_-]{0,31}$')


def execute(*args, input=None):
    return subprocess.run(args, input=input, text=True, capture_output=True, check=True,
                          timeout=30, env=ENV, cwd='/')


def trusted_file(value):
    path = Path(value).absolute()
    for item in [path, *path.parents]:
        info = item.lstat()
        expected = stat.S_ISREG(info.st_mode) if item == path else stat.S_ISDIR(info.st_mode)
        if not expected or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('Root-owned regular file and non-writable parents required')
    return path


def valid_table(table):
    if not isinstance(table, str) or not TABLE_PATTERN.fullmatch(table):
        raise ValueError('Table name must be lowercase letters, digits and underscores')
    return table


def render(config, table):
    table = valid_table(table)
    if set(config) != {'uid', 'deny_ips', 'dns_ips'}:
        raise ValueError('Unexpected configuration fields')
    if type(config['uid']) is not int or not 1 <= config['uid'] <= 4294967294:
        raise ValueError('A non-root account UID is required')
    denied = config['deny_ips']
    dns = config['dns_ips']
    # 운영 서버의 공개 IPv4는 서버마다 달라 키트 기본값이 없다. 설치할 때 하나 이상 반드시 채운다.
    if not isinstance(denied, list) or not denied:
        raise ValueError('At least one service public IP required')
    if not isinstance(dns, list) or not dns:
        raise ValueError('Explicit DNS addresses required')
    if not all(isinstance(a, str) for a in denied + dns):
        raise ValueError('IP addresses must be strings')
    blocked = [ipaddress.ip_address(a) for a in denied]
    resolvers = [ipaddress.ip_address(a) for a in dns]
    if not all(a.version == 4 and a.is_global for a in blocked):
        raise ValueError('Distinct global IPv4 service addresses required')
    if len(set(blocked)) != len(blocked) or len(set(resolvers)) != len(resolvers):
        raise ValueError('Duplicate addresses')
    if not all(a.version == 4 and not a.is_unspecified and not a.is_multicast
               and not a.is_link_local and int(a) < int(ipaddress.ip_address('224.0.0.0'))
               for a in resolvers):
        raise ValueError('Usable IPv4 DNS addresses required')
    if set(blocked) & set(resolvers):
        raise ValueError('DNS must not overlap denied service addresses')
    lines = [f'create table inet {table} {{ comment "{MARKER}"; }}',
             f'table inet {table} {{',
             ' chain output { type filter hook output priority -10; policy accept;',
             f"  meta skuid {config['uid']} jump restricted", ' }', ' chain restricted {']
    for address in sorted(blocked):
        lines.append(f'  ip daddr {address} counter reject')
    for address in sorted(resolvers):
        for protocol in ('udp', 'tcp'):
            lines.append(f'  ip daddr {address} {protocol} dport 53 counter return')
    lines.extend([
        '  meta nfproto ipv6 counter reject',
        '  ip daddr { 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, '
        '169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16, 224.0.0.0/4, 240.0.0.0/4 } counter reject',
        '  fib daddr type local counter reject',
        '  tcp dport 443 counter return', '  counter reject', ' }', '}'])
    return '\n'.join(lines) + '\n'


def network_settings(server):
    """서버 설정에서 규칙 생성에 쓰는 값만 꺼낸다. 알 수 없는 키나 빠진 키는 거부한다."""
    if not isinstance(server, dict) or set(server) != SERVER_KEYS:
        raise ValueError('Unexpected configuration fields')
    if not isinstance(server['account'], str) or not ACCOUNT_PATTERN.fullmatch(server['account']):
        raise ValueError('Invalid review account name')
    if not isinstance(server['home'], str) or not server['home'].startswith('/'):
        raise ValueError('Absolute review home required')
    network = {key: server[key] for key in ('uid', 'deny_ips', 'dns_ips')}
    return network, valid_table(server['nft_table'])


def policy(config_path):
    import pwd
    trusted_file(__file__)
    server = json.loads(trusted_file(config_path).read_text())
    network, table = network_settings(server)
    source = render(network, table)
    name = server['account']
    account = pwd.getpwnam(name)
    if (account.pw_uid != network['uid'] or account.pw_dir != server['home']
            or set(os.getgrouplist(name, account.pw_gid)) != {account.pw_gid}):
        raise ValueError('Review account UID, home or groups differ')
    return source, table


def canonical(payload):
    """dump metadata, 객체 handle과 익명 counter 값만 비교에서 제외한다."""
    table, chains, rules = None, {}, {}
    for entry in payload['nftables']:
        if set(entry) == {'metainfo'}:
            continue
        if len(entry) != 1:
            raise ValueError('Unexpected nft JSON entry')
        kind, value = next(iter(entry.items()))
        value = copy.deepcopy(value)
        value.pop('handle', None)
        if kind == 'table':
            if table is not None:
                raise ValueError('Duplicate table')
            table = value
        elif kind == 'chain':
            name = value['name']
            if name in chains:
                raise ValueError('Duplicate chain')
            chains[name] = value
        elif kind == 'rule':
            for expression in value['expr']:
                counter = expression.get('counter')
                if isinstance(counter, dict) and set(counter) == {'packets', 'bytes'}:
                    expression['counter'] = {'packets': 0, 'bytes': 0}
            rules.setdefault(value['chain'], []).append(value)
        else:
            raise ValueError('Unexpected nft object; refuse automatic adoption')
    if table is None or not chains or not rules:
        raise ValueError('Incomplete guard table')
    return {'table': table, 'chains': chains, 'rules': rules}


REFERENCE = r'''
import os, subprocess, sys
if os.readlink('/proc/self/ns/net') == sys.argv[1]:
    raise RuntimeError('Reference must not run in host network namespace')
source = sys.stdin.read()
subprocess.run(['/usr/sbin/nft', '--file', '-'], input=source, text=True, check=True, timeout=10)
subprocess.run(['/usr/sbin/nft', '-j', '-n', 'list', 'table', 'inet', sys.argv[2]],
               check=True, timeout=10)
'''


def reference(source, table):
    # 동일한 kernel/nft 버전으로 set, prefix와 암시적 reject 유형을 정규화한다.
    # 호스트 규칙은 변경하지 않으며 임시 namespace는 자식 프로세스와 함께 사라진다.
    result = execute('/usr/bin/unshare', '--net', '--', '/usr/bin/python3', '-I', '-c',
                     REFERENCE, os.readlink('/proc/self/ns/net'), valid_table(table), input=source)
    return canonical(json.loads(result.stdout))


def exists(table):
    data = json.loads(execute(NFT, '-j', 'list', 'tables').stdout)
    return any(x.get('table', {}).get('family') == 'inet'
               and x.get('table', {}).get('name') == table for x in data['nftables'])


def verify(expected, table):
    actual = canonical(json.loads(execute(NFT, '-j', '-n', 'list', 'table', 'inet', valid_table(table)).stdout))
    if actual != expected:
        raise ValueError('GUARD_MISMATCH: keep review workloads stopped; no automatic replacement')
    digest = hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()
    print('GUARD_VERIFIED: ' + digest)


def ensure(source, expected, table):
    if not exists(table):
        execute(NFT, '--check', '--file', '-', input=source)
        # create table은 동시 생성을 거부하며 기존 규칙을 병합하거나 비우지 않는다.
        execute(NFT, '--file', '-', input=source)
    verify(expected, table)
    # 재검증에 실패해도 설치한 차단 규칙은 의도적으로 유지한다.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'check', 'ensure', 'verify'], nargs='?', default='plan')
    parser.add_argument('--config', default=CONFIG)
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() != 0:
        parser.error('Linux root operator required')
    source, table = policy(args.config)
    if args.action == 'plan':
        print(source, end='')
        return
    expected = reference(source, table)
    if args.action == 'check':
        print('ISOLATED_NFT_CHECK: PASS (host firewall unchanged)')
    elif args.action == 'ensure':
        ensure(source, expected, table)
    else:
        verify(expected, table)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
        print('REVIEW_GUARD_FAILED: ' + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
