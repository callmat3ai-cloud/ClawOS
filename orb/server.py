#!/usr/bin/env python3
"""ClawOS Orb Server — serves the voice orb + status API."""
import json, os, time
from http.server import HTTPServer, SimpleHTTPRequestHandler

STATUS_FILE = '/opt/clawos/orb/status.json'
START_TIME = time.time()

class OrbHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/status':
            # Read current status
            try:
                with open(STATUS_FILE) as f:
                    status = json.load(f)
            except Exception:
                status = {"status": "idle", "message": "ClawOS is online"}
            status['uptime_seconds'] = int(time.time() - START_TIME)
            status['agents_active'] = 8
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(status).encode())
        else:
            super().do_GET()

    def log_message(self, format, *args):
        pass  # Silent

if __name__ == '__main__':
    os.chdir('/opt/clawos/orb')
    server = HTTPServer(('0.0.0.0', 8081), OrbHandler)
    print("ClawOS Orb Server running on :8081")
    server.serve_forever()
