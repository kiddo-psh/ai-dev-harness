"""core/ci/claude-review/sandbox-probe.py (feelm test_sandbox_probe.py 이관)."""

import importlib.util
from pathlib import Path
import unittest

BASE = Path(__file__).resolve().parent.parent / 'core' / 'ci' / 'claude-review'
EXAMPLES = BASE / 'examples'
spec = importlib.util.spec_from_file_location('sandbox_probe', BASE / 'sandbox-probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class SandboxProbeTests(unittest.TestCase):
    def test_limits_reject_unbounded_or_different_resources(self):
        values = {'cpu.max': '100000 100000', 'memory.high': str(2 * 1024**3),
                  'memory.max': str(3 * 1024**3), 'memory.swap.max': '0', 'pids.max': '128'}
        self.assertTrue(probe.limits_match(values))
        self.assertTrue(probe.limits_match(dict(values, **{'cpu.max': '10000 10000'})))
        for key, changed in [('cpu.max', 'max 100000'), ('cpu.max', '200000 100000'),
                             ('memory.max', 'max'), ('memory.high', 'max'),
                             ('memory.swap.max', 'max'), ('pids.max', 'max')]:
            with self.subTest(key=key, changed=changed):
                self.assertFalse(probe.limits_match(dict(values, **{key: changed})))

    def test_probe_and_runner_have_identical_sandbox_settings(self):
        differing = {'Description', 'Type', 'ExecStart', 'Restart', 'RestartSec',
                     'TimeoutStartSec', 'WantedBy', 'ConditionPathExists'}
        def settings(name):
            return [line for line in (EXAMPLES / name).read_text(encoding='utf-8').splitlines()
                    if '=' in line and not line.startswith('#')
                    and line.split('=', 1)[0] not in differing]
        self.assertEqual(settings('claude-review-runner.service.example'),
                         settings('claude-review-probe.service.example'))
        source = (EXAMPLES / 'claude-review-probe.service.example').read_text(encoding='utf-8')
        self.assertNotIn('ExecStart=/usr/bin/gitlab-runner', source)
        self.assertNotIn('[Install]', source)


if __name__ == '__main__':
    unittest.main()
