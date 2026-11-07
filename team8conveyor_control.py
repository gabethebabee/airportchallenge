"""Optional HTTP adapter to team8conveyor_flow.json on the PLC. No PLC writes here."""
import json
import os
import threading
import urllib.request
from urllib.error import HTTPError
from urllib.parse import urlparse


class ConveyorControl:
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


# Comment this line out (or keep the default False) to remove all hardware access.
ENABLE_CONVEYOR_CONTROL = False
