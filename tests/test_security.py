import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import monitor


WEBHOOK = 'https://' + 'discord.com/api/webhooks/' + '123456789/synthetic_test_token'
SCANNER = Path(__file__).resolve().parents[1] / 'scripts' / 'check_secrets.py'


class WebhookTests(unittest.TestCase):
    def test_only_environment_references_are_accepted(self):
        with patch.dict(os.environ, {'TEST_WEBHOOK': WEBHOOK}):
            self.assertEqual(monitor.resolve_webhook('$TEST_WEBHOOK'), WEBHOOK)
        for value in (WEBHOOK, '', None, '$INVALID-NAME'):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(ValueError) as error:
                    monitor.resolve_webhook(value)
                self.assertNotIn(WEBHOOK, str(error.exception))
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'is not set'):
                monitor.resolve_webhook('$TEST_WEBHOOK')

    def test_webhook_is_passed_on_stdin_not_in_command(self):
        with patch.object(monitor.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, '204', '')
            self.assertEqual(monitor.send_discord(WEBHOOK, {}), 204)
        self.assertNotIn(WEBHOOK, repr(run.call_args.args[0]))
        self.assertIn(WEBHOOK, run.call_args.kwargs['input'])

    def test_transport_failures_are_safe_and_explicit(self):
        for failure in (
            subprocess.TimeoutExpired(['curl', WEBHOOK], 15),
            OSError(WEBHOOK),
        ):
            with patch.object(monitor.subprocess, 'run', side_effect=failure):
                with self.assertRaises(RuntimeError) as error:
                    monitor.send_discord(WEBHOOK, {})
                self.assertNotIn(WEBHOOK, str(error.exception))
        for code, status in ((7, '000'), (0, '401'), (0, '429'), (0, '500'), (0, '')):
            with self.subTest(code=code, status=status):
                with patch.object(monitor.subprocess, 'run') as run:
                    run.return_value = subprocess.CompletedProcess([], code, status, WEBHOOK)
                    with self.assertRaises(RuntimeError) as error:
                        monitor.send_discord(WEBHOOK, {})
                    self.assertNotIn(WEBHOOK, str(error.exception))

    def test_logging_redacts_webhooks_in_stdout_and_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with patch.object(monitor, 'LOGS_DIR', Path(directory)):
                with contextlib.redirect_stdout(output):
                    monitor.log('test', f"ERROR: {WEBHOOK}")
            file_output = (Path(directory) / 'test.log').read_text()
        for text in (output.getvalue(), file_output):
            self.assertNotIn(WEBHOOK, text)
            self.assertIn('[REDACTED DISCORD WEBHOOK]', text)

    def test_failed_alert_keeps_previous_snapshot_for_retry(self):
        site = {
            'id': 'test', 'name': 'Test', 'type': 'generic',
            'url': 'https://example.com', 'discord_webhook': '$TEST_WEBHOOK',
        }
        with patch.object(monitor, 'load_extractor') as extractor, \
                patch.object(monitor, 'load_snapshot', return_value={'page': {'hash': 'old'}}), \
                patch.object(monitor, 'save_snapshot') as save, \
                patch.object(monitor, 'send_discord', side_effect=RuntimeError('Discord request timed out')), \
                patch.object(monitor, 'log') as log, \
                patch.dict(os.environ, {'TEST_WEBHOOK': WEBHOOK}):
            extractor.return_value.extract.return_value = {'page': {'hash': 'new'}}
            self.assertFalse(monitor.run_site(site))
            save.assert_not_called()
            self.assertIn('ERROR sending Discord notification', log.call_args.args[1])

    def test_failed_heartbeat_does_not_mark_day_as_sent(self):
        config = {'heartbeat': {'hour': 0, 'discord_webhook': '$TEST_WEBHOOK'}}
        with patch.object(monitor, 'load_heartbeat_state', return_value={}), \
                patch.object(monitor, 'save_heartbeat_state') as save, \
                patch.object(monitor, 'send_discord', side_effect=RuntimeError('Discord request timed out')), \
                patch.object(monitor, 'log') as log, \
                patch.dict(os.environ, {'TEST_WEBHOOK': WEBHOOK}):
            monitor.maybe_send_heartbeat(config, [], 1)
            self.assertNotIn('last_sent_date', save.call_args.args[0])
            self.assertEqual(save.call_args.args[0]['changes_since'], 1)
            self.assertIn('ERROR sending heartbeat', log.call_args.args[1])


class SecretGuardTests(unittest.TestCase):
    def test_scans_staged_content_and_never_prints_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            def git(*args):
                return subprocess.run(
                    ['git', *args], cwd=directory, check=True, capture_output=True,
                )

            def scan():
                return subprocess.run(
                    ['python3', str(SCANNER)], cwd=directory,
                    capture_output=True, text=True,
                )

            git('init', '--quiet')
            path = Path(directory) / 'config.json'
            path.write_text('{"discord_webhook": "$TEST_WEBHOOK"}')
            git('add', 'config.json')
            self.assertEqual(scan().returncode, 0)
            for url in (
                WEBHOOK,
                WEBHOOK.replace('discord.com', 'discordapp.com'),
                WEBHOOK.replace('discord.com/api/', 'canary.discord.com/api/v10/'),
            ):
                path.write_text(url)
                git('add', 'config.json')
                path.write_text('safe but not staged')
                result = scan()
                self.assertEqual(result.returncode, 1)
                self.assertIn('config.json', result.stderr)
                self.assertNotIn(url, result.stderr + result.stdout)
                self.assertNotIn('synthetic_test_token', result.stderr + result.stdout)


if __name__ == '__main__':
    unittest.main()
