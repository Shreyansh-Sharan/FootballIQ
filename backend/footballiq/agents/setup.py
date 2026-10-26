"""footballiq-agents CLI: set up, list and smoke-test the Foundry agents.

The printed agent id env lines are optional; the API finds agents by name.
"""

from __future__ import annotations

import argparse
import json
import sys

from footballiq import config
from footballiq.agents.definitions import AGENTS
from footballiq.agents.foundry import FoundryClient, default_model


def main() -> None:
    ap = argparse.ArgumentParser(prog="footballiq-agents")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup")
    s.add_argument("--model", default=None, help=f"deployment name (default FOUNDRY_MODEL or {default_model()})")
    sub.add_parser("list")
    sub.add_parser("models")
    a = sub.add_parser("ask")
    a.add_argument("question")
    a.add_argument("--match", default="2022-12-18_argentina_france")
    a.add_argument("--at-ms", type=int, default=4_500_000)
    a.add_argument("--agent", choices=sorted(AGENTS), default="strategist")
    args = ap.parse_args()
    config.load_dotenv()

    fc = FoundryClient()
    if args.cmd == "setup":
        for spec in AGENTS.values():
            agent = fc.ensure_agent(spec, args.model)
            print(f"{spec.name}: {agent['id']} (model {agent['model']})", file=sys.stderr)
            print(f"FOUNDRY_AGENT_{spec.key.upper()}_ID={agent['id']}")
    elif args.cmd == "list":
        for a in fc.list_agents():
            print(f"{a['id']}  {a.get('name')}  model={a.get('model')}  tools={[t.get('function', {}).get('name') for t in a.get('tools', [])]}")
    elif args.cmd == "models":
        for d in fc._req("GET", "/deployments").get("value", []):
            print(f"{d['name']:28} {d.get('modelPublisher', ''):10} {json.dumps(d.get('capabilities', {}))}")
    else:
        from footballiq.agents.service import AgentService
        from footballiq.store import default_store

        svc = AgentService(default_store(), fc)
        out = svc.ask(args.match, args.at_ms, args.question) if args.agent == "strategist" else svc.explain(args.match, args.at_ms)
        print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
