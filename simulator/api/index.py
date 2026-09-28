from http.server import BaseHTTPRequestHandler
import json
import sys
from pathlib import Path

# Add simulator/src to path for kinesis modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

try:
    from kinesis.scenario import load_scenario
    from kinesis.demo import run_demo
except ImportError:
    load_scenario = None
    run_demo = None


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        payload = {
            "service": "simulator",
            "status": "online",
            "engine": "kinesis-sipp-consensus",
            "runtime": "python"
        }
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        payload = {
            "service": "simulator",
            "status": "ready",
            "message": "kinesis simulation task accepted"
        }
        self.wfile.write(json.dumps(payload).encode("utf-8"))
