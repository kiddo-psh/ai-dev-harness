#!/usr/bin/env python3
"""고정된 Claude 요청 하나만 보내며 CLI 원문과 인증 정보를 기록하지 않는다."""
import json
import os
import sys
import types
from pathlib import Path
import subprocess
import tempfile

# 공통 코드는 원본에서 직접 컴파일한다. importlib 로더는 __pycache__의 바이트코드를 원본과 대조하지 않고
# 쓸 수 있어, check가 보지 않는 .pyc 하나로 신뢰 판정을 바꿀 수 있다.
_COMMON_PATH = Path(__file__).resolve().with_name('review_common.py')
common = types.ModuleType('harness_review_common')
common.__file__ = str(_COMMON_PATH)
sys.modules['harness_review_common'] = common
exec(compile(_COMMON_PATH.read_bytes(), str(_COMMON_PATH), 'exec'), common.__dict__)

# 스크립트는 대상 저장소의 `.harness/claude-review/`에 있다. 저장소 루트의 harness.json이 정책이다.
ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / 'harness.json'
PROMPT = 'Reply with exactly OK. Do not use tools or read files.'


def context_valid(env, policy):
    # 인증 검사는 push·web 파이프라인에서만 수동으로 돈다. api 트리거는 받지 않는다.
    return common.trusted_context(env, policy, allow_api_trigger=False)


def child_environment(credential_name, token, home):
    # 고른 자격 증명 하나만 넘긴다. 다른 자격 증명, GitLab 인증 정보, proxy와 프로젝트 환경변수는 전달하지 않는다.
    return common.child_environment(credential_name, token, home)


def command(claude_cli):
    return [claude_cli, *common.CLI_ARGS]


def classify(result):
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError):
        data = None
    if (result.returncode == 0 and isinstance(data, dict)
            and data.get('type') == 'result' and data.get('subtype') == 'success'
            and data.get('is_error') is False and isinstance(data.get('result'), str)
            and data['result'].strip() == 'OK'):
        return 'PASS'
    # 휴리스틱은 진단 분류에만 사용하며 원문 응답은 출력하지 않는다.
    text = (str(result.stdout) + str(result.stderr)).lower()
    if any(word in text for word in ['rate_limit', 'rate limit', 'usage limit', '429']):
        return 'USAGE_LIMIT'
    if any(word in text for word in ['unauthorized', 'authentication', 'invalid token', '401', 'login expired']):
        return 'AUTHENTICATION_FAILED'
    return 'REQUEST_FAILED_OR_UNEXPECTED_RESPONSE'


def main():
    try:
        policy = common.load_policy(POLICY_PATH)
        if not context_valid(os.environ, policy):
            raise common.ReviewError('REJECTED_CI_CONTEXT')
        # 서버 설정을 확인한 뒤에야 자격 증명을 읽는다.
        server = common.load_server_config(common.server_config_path(policy))
        credential_name, token = common.read_credential(os.environ, policy)
    except common.ReviewError as error:
        print('CLAUDE_AUTH_CHECK: ' + error.code)
        return 1
    with tempfile.TemporaryDirectory(prefix='harness-claude-auth-') as directory:
        home = Path(directory)
        try:
            # 빈 작업·홈 디렉터리로 저장소 에이전트 설정과 사용자 로그인 상태를 읽지 않는다.
            result = subprocess.run(command(server['claude_cli']), input=PROMPT, text=True,
                                    capture_output=True, cwd=home,
                                    env=child_environment(credential_name, token, home),
                                    timeout=policy['timeouts']['auth_check_seconds'])
            status = classify(result)
        except subprocess.TimeoutExpired:
            status = 'TIMEOUT'
        except OSError:
            status = 'CLI_EXECUTION_FAILED'
    print('CLAUDE_AUTH_CHECK: ' + status)
    return 0 if status == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
