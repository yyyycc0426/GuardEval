#!/usr/bin/env python
import argparse
import logging
import sys
from pathlib import Path

# Setup path and logging
sys.path.insert(0, str(Path(__file__).resolve().parent))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from llm_security_platform.app.providers import build_provider
from llm_security_platform.app.crescendo import CrescendoOrchestrator

def main():
    parser = argparse.ArgumentParser(description="Run Crescendo multi-turn red-teaming orchestrator")
    parser.add_argument("--objective", type=str, default="injection_succeeded", help="Jailbreak objective keyword")
    parser.add_argument("--turns", type=int, default=4, help="Maximum dialog turns")
    parser.add_argument("--provider", type=str, default="mock", help="Target model provider")
    parser.add_argument("--model", type=str, default="mock-vulnerable-model", help="Target model name")
    args = parser.parse_args()

    # Build target model client
    target_provider = build_provider(args.provider, args.model)
    
    # We will use mock as the attacker provider to generate structured crescendo prompts
    attacker_provider = build_provider("mock", "attacker-helper")

    orchestrator = CrescendoOrchestrator(
        attacker_provider=attacker_provider,
        target_provider=target_provider,
        objective=args.objective,
        max_turns=args.turns
    )

    print("======================================================================")
    print(f"Starting Multi-Turn Crescendo Red Teaming Session")
    print(f"Objective: {args.objective}")
    print(f"Target:    {args.provider}/{args.model}")
    print("======================================================================\n")

    result = orchestrator.run()

    print("\n======================================================================")
    print("Session Results Summary")
    print(f"Success:      {result['success']}")
    print(f"Total Turns:  {result['total_turns']}")
    print("======================================================================")
    for entry in result["dialogue"]:
        print(f"\n[Turn {entry['turn']}]")
        print(f"  > PROMPT:   {entry['prompt']}")
        print(f"  < RESPONSE: {entry['response']}")
        print(f"  * Refused:  {entry['refused']}")
    print("======================================================================\n")

if __name__ == "__main__":
    main()
