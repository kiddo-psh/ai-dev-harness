"""core/ci/claude-review/auth-check.py (feelm test_auth_check.py 이관)."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent.parent / "core" / "ci" / "claude-review"
spec = importlib.util.spec_from_file_location('auth_check', SCRIPTS / 'auth-check.py')
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)

POLICY = auth.common.validate_policy({'target_branch': 'develop', 'credential': 'oauth'})
SERVER = {'claude_cli': '/opt/review/claude', 'workdir': '/tmp/review'}


@contextlib.contextmanager
def configured():
    with patch.object(auth.common, 'load_policy', return_value=POLICY), \
            patch.object(auth.common, 'load_server_config', return_value=SERVER):
        yield


class AuthCheckTests(unittest.TestCase):
    def setUp(self):
        self.env = {'CI_COMMIT_BRANCH': 'develop', 'CI_COMMIT_REF_PROTECTED': 'true',
                    'CI_ENVIRONMENT_NAME': 'claude-review', 'CI_PIPELINE_SOURCE': 'web',
                    'CLAUDE_CODE_OAUTH_TOKEN': 'synthetic-secret'}

    def test_rejects_mr_unprotected_and_debug_contexts(self):
        for key, value in [('CI_COMMIT_BRANCH', 'feat/example'),
                           ('CI_COMMIT_REF_PROTECTED', 'false'),
                           ('CI_PIPELINE_SOURCE', 'merge_request_event'),
                           ('CI_ENVIRONMENT_NAME', 'service'), ('CI_DEBUG_TRACE', 'true')]:
            with self.subTest(key=key):
                self.assertFalse(auth.context_valid(dict(self.env, **{key: value}), POLICY))

    def test_child_only_receives_allowlisted_environment(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'wrong-account', 'CI_JOB_TOKEN': 'gitlab-secret'}):
            env = auth.child_environment('CLAUDE_CODE_OAUTH_TOKEN', 'synthetic-secret', Path('/tmp/example'))
        self.assertNotIn('ANTHROPIC_API_KEY', env)
        self.assertNotIn('CI_JOB_TOKEN', env)
        self.assertEqual(env['CLAUDE_CODE_OAUTH_TOKEN'], 'synthetic-secret')

    def test_accepts_only_successful_fixed_response(self):
        payload = dict(type='result', subtype='success', is_error=False, result='OK')
        self.assertEqual(auth.classify(subprocess.CompletedProcess([], 0, json.dumps(payload), '')), 'PASS')
        for changed in [dict(payload, is_error=True), dict(payload, result='other'),
                        dict(payload, subtype='error_max_turns')]:
            self.assertNotEqual(auth.classify(subprocess.CompletedProcess([], 0, json.dumps(changed), '')), 'PASS')

    def test_error_never_prints_raw_output_or_secret(self):
        output = io.StringIO()
        failure = subprocess.CompletedProcess([], 1, '401 synthetic-secret', 'private response')
        with patch.dict(os.environ, self.env, clear=True), configured(), \
                patch.object(auth.subprocess, 'run', return_value=failure), contextlib.redirect_stdout(output):
            self.assertEqual(auth.main(), 1)
        self.assertEqual(output.getvalue(), 'CLAUDE_AUTH_CHECK: AUTHENTICATION_FAILED\n')

    def test_missing_token_never_launches_cli(self):
        with patch.dict(os.environ, dict(self.env, CLAUDE_CODE_OAUTH_TOKEN=''), clear=True), configured(), \
                patch.object(auth.subprocess, 'run') as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(auth.main(), 1)
            run.assert_not_called()

    def test_timeout_is_reported_without_raw_output(self):
        output = io.StringIO()
        with patch.dict(os.environ, self.env, clear=True), configured(), \
                patch.object(auth.subprocess, 'run', side_effect=subprocess.TimeoutExpired('claude', 120, output='secret')), \
                contextlib.redirect_stdout(output):
            self.assertEqual(auth.main(), 1)
        self.assertEqual(output.getvalue(), 'CLAUDE_AUTH_CHECK: TIMEOUT\n')


if __name__ == '__main__':
    unittest.main()
