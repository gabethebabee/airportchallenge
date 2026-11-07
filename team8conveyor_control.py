"""Optional HTTP adapter to team8conveyor_flow.json on the PLC. No PLC writes here."""
import json
import os
import threading
import urllib.request
from urllib.error import HTTPError
from urllib.parse import urlparse


# Optional adapter for the separate PLC control bridge; monitoring does not depend on enabling
# it.
# This adapter exists only for explicitly enabled physical-control requests. Monitoring can run
# with it disabled, and its token/base URL remain in Python rather than being embedded into
# downloadable browser code.
class ConveyorControl:
    # Validate connection settings only when control is explicitly enabled; never store the
    # token in the page.
    # The enabled flag defaults off. If enabled, the URL shape and minimum token length are
    # checked before any request is permitted; merely constructing the disabled adapter does not
    # contact the PLC.
    def __init__(self, enabled=False):
        self.enabled = enabled
        self.base = os.environ.get('TEAM8_PLC_URL', '').rstrip('/')
        self.token = os.environ.get('TEAM8_CONTROL_TOKEN', '')
        self.lock = threading.Lock()
        if enabled:
            url = urlparse(self.base)
            if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.query or url.fragment:
                raise ValueError('Set TEAM8_PLC_URL to the Node-RED HTTP base URL')
            if len(self.token) < 24:
                raise ValueError('TEAM8_CONTROL_TOKEN must have at least 24 characters; also set it in Node-RED')

    # Allow only status/run/stop and never retry a physical command whose outcome may be
    # uncertain.
    # Only status, run and stop are accepted. The authenticated HTTP request goes to the
    # separate Node-RED bridge; known rejections are distinguishable from timeouts, where a
    # physical command may already have executed and must not be retried automatically.
    def request(self, action):
        if action not in ('status', 'run', 'stop'):
            raise ValueError('Unknown conveyor action')
        if not self.enabled:
            return {'enabled': False, 'message': 'Hardware control disabled; no command sent.'}
        # Never retry a run after a timeout: the output may already have changed.
        with self.lock:
            request = urllib.request.Request(
                self.base + '/team8/conveyor',
                data=json.dumps({'action': action}).encode(),
                headers={'Content-Type': 'application/json', 'X-Team8-Token': self.token},
                method='POST')
            try:
                with urllib.request.urlopen(request, timeout=3) as response:
                    result = json.loads(response.read(32768))
            except HTTPError as error:
                # A route/token rejection is different from a timeout with unknown outcome.
                result = json.loads(error.read(32768))
                result['rejected'] = True
            if not isinstance(result, dict):
                raise ValueError('Invalid PLC response')
            return {'enabled': True, **result}


# Keep False to disable hardware access, or comment out the optional dashboard import.
ENABLE_CONVEYOR_CONTROL = False
