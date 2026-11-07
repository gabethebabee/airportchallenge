"""Offline tests only. Run: python -B -m unittest team8test_control"""
import io
import json
import os
import unittest
from unittest.mock import patch, MagicMock

import team8conveyor_control as control
import team8dashboard as dashboard


# Group the related offline regression checks so failures identify the affected feature.
# These regression scenarios group the behavior of this feature in isolation. Shared setup
# supplies temporary/in-memory state; no test is allowed to depend on a running physical
# conveyor. A failure identifies a broken assumption before deployment.
class ControlTests(unittest.TestCase):
    # Regression check: disabled never connects. Uses fakes/in-memory state, never live
    # equipment.
    # This scenario exercises disabled never connects. The setup uses controlled inputs and a
    # fake clock or mocked request instead of contacting a broker, camera or PLC. Assertions
    # below define the result that must continue working after future edits.
    def test_disabled_never_connects(self):
        with patch.object(control.urllib.request, 'urlopen') as connection:
            self.assertFalse(control.ConveyorControl().request('run')['enabled'])
            connection.assert_not_called()

    # Regression check: enabled requires configuration. Uses fakes/in-memory state, never live
    # equipment.
    # This scenario exercises enabled requires configuration. The setup uses controlled inputs
    # and a fake clock or mocked request instead of contacting a broker, camera or PLC.
    # Assertions below define the result that must continue working after future edits.
    def test_enabled_requires_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                control.ConveyorControl(True)

    # Regression check: command contract and no retry. Uses fakes/in-memory state, never live
    # equipment.
    # This scenario exercises command contract and no retry. The setup uses controlled inputs
    # and a fake clock or mocked request instead of contacting a broker, camera or PLC.
    # Assertions below define the result that must continue working after future edits.
    def test_command_contract_and_no_retry(self):
        with patch.dict(os.environ, {'TEAM8_PLC_URL': 'https://plc.example', 'TEAM8_CONTROL_TOKEN': 'x'*32}):
            adapter = control.ConveyorControl(True)
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"message":"requested"}'
        with patch.object(control.urllib.request, 'urlopen', return_value=response) as connection:
            self.assertTrue(adapter.request('stop')['enabled'])
            request = connection.call_args.args[0]
            self.assertEqual(request.full_url, 'https://plc.example/team8/conveyor')
            self.assertEqual(json.loads(request.data), {'action': 'stop'})
        with patch.object(control.urllib.request, 'urlopen', side_effect=TimeoutError) as connection:
            with self.assertRaises(TimeoutError):
                adapter.request('run')
            self.assertEqual(connection.call_count, 1)

    # Regression check: http rejection is not unknown timeout. Uses fakes/in-memory state, never
    # live equipment.
    # This scenario exercises http rejection is not unknown timeout. The setup uses controlled
    # inputs and a fake clock or mocked request instead of contacting a broker, camera or PLC.
    # Assertions below define the result that must continue working after future edits.
    def test_http_rejection_is_not_unknown_timeout(self):
        with patch.dict(os.environ, {'TEAM8_PLC_URL': 'https://plc.example', 'TEAM8_CONTROL_TOKEN': 'x'*32}):
            adapter = control.ConveyorControl(True)
        error = control.HTTPError('https://plc.example', 409, 'Rejected', {}, io.BytesIO(b'{"message":"Scan required"}'))
        with patch.object(control.urllib.request, 'urlopen', side_effect=error):
            self.assertTrue(adapter.request('run')['rejected'])

    # Build an in-memory HTTP handler so authorization/routes can be tested without a network
    # connection.
    # Construct an HTTP handler around byte buffers and mocked headers/response methods. The
    # real route code can then be exercised without opening a network socket or permitting a
    # physical output request.
    def handler(self, host='127.0.0.1:8080', token=None, body=b'{"action":"run"}'):
        h=object.__new__(dashboard.DashboardHandler)
        h.path='/api/conveyor'
        h.server=MagicMock(server_port=8080)
        h.headers={'Host':host,'Content-Length':str(len(body)), 'X-Team8-Session':token or ''}
        h.rfile=io.BytesIO(body)
        h.wfile=io.BytesIO()
        h.send_response=MagicMock()
        h.send_header=MagicMock()
        h.end_headers=MagicMock()
        return h

    # Regression check: rejects cross host and missing session. Uses fakes/in-memory state,
    # never live equipment.
    # This scenario exercises rejects cross host and missing session. The setup uses controlled
    # inputs and a fake clock or mocked request instead of contacting a broker, camera or PLC.
    # Assertions below define the result that must continue working after future edits.
    def test_rejects_cross_host_and_missing_session(self):
        for h in [self.handler(), self.handler(host='evil.example',token=dashboard.CONTROL_SESSION)]:
            h.do_POST()
            h.send_response.assert_called_once_with(403)

    # Regression check: api disabled no actuation. Uses fakes/in-memory state, never live
    # equipment.
    # This scenario exercises api disabled no actuation. The setup uses controlled inputs and a
    # fake clock or mocked request instead of contacting a broker, camera or PLC. Assertions
    # below define the result that must continue working after future edits.
    def test_api_disabled_no_actuation(self):
        h=self.handler(token=dashboard.CONTROL_SESSION)
        with patch.object(dashboard,'CONTROL',None): h.do_POST()
        self.assertFalse(json.loads(h.wfile.getvalue())['enabled'])

    # Regression check: api invalid action. Uses fakes/in-memory state, never live equipment.
    # This scenario exercises api invalid action. The setup uses controlled inputs and a fake
    # clock or mocked request instead of contacting a broker, camera or PLC. Assertions below
    # define the result that must continue working after future edits.
    def test_api_invalid_action(self):
        h=self.handler(token=dashboard.CONTROL_SESSION,body=b'{"action":"reverse"}')
        h.do_POST()
        h.send_response.assert_called_once_with(400)


if __name__ == '__main__':
    unittest.main()
