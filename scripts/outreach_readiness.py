#!/usr/bin/env python3
"""Inspect config safely. Network requires the explicit --probe-local-models flag."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.readiness import readiness, probe_models


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe-local-models', action='store_true', help='Explicitly issue GET /models to configured loopback model endpoints; never run inference.')
    args = parser.parse_args()
    report = readiness()
    if args.probe_local_models:
        probes = {'draft_model': probe_models(os.environ.get('AFTERWORD_LLM_URL', 'http://127.0.0.1:8000/v1'), os.environ.get('AFTERWORD_LLM_MODEL', ''))}
        vision = os.environ.get('AFTERWORD_VISION_ENDPOINT', '')
        if vision.endswith('/chat/completions'):
            probes['vision_model'] = probe_models(vision.removesuffix('/chat/completions'), os.environ.get('AFTERWORD_VISION_MODEL', ''))
        else:
            probes['vision_model'] = {'attempted': False, 'reason': 'No compatible local vision endpoint is configured.'}
        report['explicit_local_probes'] = probes
        report['network_requests'] = sum(item.get('attempted', False) for item in probes.values())
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
