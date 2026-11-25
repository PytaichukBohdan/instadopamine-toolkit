import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

SCRIPT = Path(__file__).parents[1] / 'scripts/deploy_report.py'
spec = importlib.util.spec_from_file_location('deploy_report', SCRIPT)
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


def response(data):
    r = Mock(status_code=200, ok=True)
    r.json.return_value = data
    return r


class ProtectedDeploymentTests(unittest.TestCase):
    def run_deploy(self, fail_open=False, https_error=False, extra=()):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); site = root / 'site'; site.mkdir()
            for name in ['style.css', 'search.js', 'search-index.json', 'coverage.json', 'source-inventory.json']:
                (site / name).write_text('{}')
            shutil.copyfile(SCRIPT.parents[1] / 'instadna/web/_worker.js', site / '_worker.js')
            (site / '_routes.json').write_text(json.dumps({'version': 1, 'include': ['/*'], 'exclude': []}))
            config = root / 'private.json'
            config.write_text(json.dumps({'project': 'private-test', 'account_id': 'account', 'username': 'owner', 'password': 'test-only'}))
            env = {'fail_open': fail_open, 'env_vars': {k: {'type': 'secret_text'} for k in ['REPORT_USERNAME', 'REPORT_PASSWORD']}}
            session = Mock()
            session.headers = {}
            session.get.side_effect = [response({}), response({'result': {'deployment_configs': {'production': env, 'preview': env}}}), response({'result': [{'url': 'https://deadbeef.private-test.pages.dev', 'aliases': None}]})]
            session.patch.return_value = response({'success': True})
            cmd = Mock(return_value=Mock(returncode=0, stdout='https://deadbeef.private-test.pages.dev', stderr=''))
            def fetch(url, **kwargs):
                if https_error:
                    raise requests.exceptions.SSLError('test TLS failure')
                return Mock(status_code=200 if kwargs.get('auth') else 401, headers={'Cache-Control': 'private, no-store'})
            with patch.object(deploy.requests, 'Session', return_value=session), patch.object(deploy.requests, 'get', side_effect=fetch) as get, patch.object(deploy.subprocess, 'run', cmd), patch.object(deploy.time, 'sleep'), patch.dict(os.environ, {'CLOUDFLARE_API_TOKEN': 'test-only-token'}), patch('sys.argv', ['deploy', '--directory', str(site), '--private-config', str(config), '--project', 'private-test', '--account-id', 'account', *extra]), contextlib.redirect_stdout(io.StringIO()):
                error = None
                try:
                    deploy.main()
                except SystemExit as e:
                    error = str(e)
            return session, cmd, get, error

    def test_requires_platform_fail_closed_before_upload(self):
        session, cmd, get, error = self.run_deploy(fail_open=True)
        self.assertIn('must fail closed', error)
        cmd.assert_not_called()
        get.assert_not_called()
        settings = session.patch.call_args.kwargs['json']['deployment_configs']
        self.assertEqual(set(settings), {'production', 'preview'})
        self.assertTrue(all(v['fail_open'] is False for v in settings.values()))

    def test_verifies_actual_deployment_without_inventing_main_alias(self):
        session, cmd, get, error = self.run_deploy()
        self.assertIsNone(error)
        cmd.assert_called_once()
        urls = [call.args[0] for call in get.call_args_list]
        self.assertEqual(len(urls), 24)
        self.assertFalse(any('main.private-test' in url for url in urls))
        self.assertTrue(any('deadbeef.private-test' in url for url in urls))

    def test_transient_https_error_never_triggers_duplicate_deployment(self):
        session, cmd, get, error = self.run_deploy(https_error=True)
        self.assertIn('Retry verification; do not redeploy', error)
        cmd.assert_called_once()
        self.assertEqual(get.call_count, 5)

    def test_custom_verification_paths_must_exist_in_the_prepared_site(self):
        session, cmd, get, error = self.run_deploy(extra=['--verify-path', '/', '--verify-path', '/coverage.json'])
        self.assertIsNone(error)
        self.assertEqual(len(get.call_args_list), 8)
        session, cmd, get, error = self.run_deploy(extra=['--verify-path', '/missing.css'])
        self.assertIn('not a file of the prepared site', error)
        cmd.assert_not_called()
