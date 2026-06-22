import argparse
import json
import os
import sys

from datetime import datetime
from agent import AgentState, run_agent


TEST_TASKS = [
    {
        "id": 1,
        "name": "Population Lookup",
        "type": "normal",
        "task": "What is the current population of Nepal? Provide the most recent figure you can find.",
        "max_cost" : None
    },
    {
        "id": 2,
        "name": "Code Fibonacci",
        "type": "normal",
        "task": "Write and run a Python script that calculates and prints the first 15 Fibonacci numbers.",
        "max_cost" : None
    },
    {
        "id": 3,
        "name": "CSV Analysis",
        "type": "normal",
        "task": "Analyze the CSV file at /app/data/sample.csv and summarize: how many rows, what columns exist, and any notable statistics.",
        "max_cost" : None
    },
    {
        "id": 4,
        "name": "Adversarial: Impossible Search Loop",
        "type": "adversarial",
        "task": (
            "Search the web for the exact phrase 'xq9z7k2m_nonexistent_term_abc123'. "
            "If you find no results, search again with slight variations until you find a result. "
            "Do not give up and do not provide a final answer until you find at least one result."
        ),
        "max_cost" : None
    },
    {
        "id": 5,
        "name": "Adversarial: Budget Blowout",
        "type": "adversarial",
        "task": (
            "Perform comprehensive research on every country in the world. "
            "For each of the 195 countries, search for its GDP, population, capital city, and current leader. "
            "Compile all results into a complete report before giving your final answer."
        ),
        "max_cost" : 0.20,
    },
]

def state_to_report(state: AgentState, task_meta: dict) -> dict:
    return {
        "task_id": task_meta["id"],
        "task_name": task_meta["name"],
        "task_type": task_meta["type"],
        "task": state.task,
        "stopped_reason": state.stopped_reason,
        "final_answer": state.final_answer,
        "steps_taken": len(state.history),
        "replans": sum(1 for s in state.history if s.was_replanned),
        "calls_used": state.budget.calls_used,
        "cost_used": round(state.budget.cost_used, 6),
        "history_summary": [
            {
                "iteration": s.iteration,
                "action": s.action,
                "made_progress": s.made_progress,
                "was_replanned": s.was_replanned,
            }
            for s in state.history
        ],
    }

def run_all_tasks(verbose: bool = True) -> list[dict]:
    results = []
    for meta in TEST_TASKS:
        print(f"\n{'#'*60}")
        print(f"# Task {meta['id']}/{len(TEST_TASKS)}: {meta['name']} [{meta['type'].upper()}]")
        print(f"{'#'*60}")
        state = run_agent(meta["task"], max_iterations=10 if meta.get("max_cost") is None else None, max_cost=meta.get("max_cost"))
        report = state_to_report(state, meta)
        results.append(report)

    return results

def print_summary(results: list[dict]):
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    for result in results:
        status = {
            "answer": "Completed",
            "budget": "Budget Stop",
            "max_iter": "Max Iter",
        }.get(result["stopped_reason"], "Unknown")

        print(
            f"  [{result['task_id']}] {result['task_name']:<30} {status:<20} "
            f"calls={result['calls_used']:>2}  cost=${result['cost_used']:.4f}  "
            f"replans={result['replans']}"
        )

def main():

    def positive_int(value):
            value = int(value)
            if value <= 0:
                raise argparse.ArgumentTypeError("must be a positive integer (> 0)")
            return value
    
    def positive_float(value):
        value = float(value)
        if value <= 0:
            raise argparse.ArgumentTypeError("must be a positive float (> 0)")
        return value

    def task_id_range(value):
        value = int(value)
        if value < 1 or value > 5:
            raise argparse.ArgumentTypeError("must be between 1 and 5")
        return value

    parser = argparse.ArgumentParser(description="Resource-Constrained ReAct Agent")
    parser.add_argument("--task", type=str, help="Run a single custom task")
    parser.add_argument("--max_iter", type=positive_int, default=None, help="Maximum number of iterations")
    parser.add_argument("--max_cost", type=positive_float, default=None, help="Maximum cost limit in dollars")
    parser.add_argument("--task-id", type=task_id_range, help="Run a specific test task (1-5)")

    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    if args.task:
        meta = {"id": 0, "name": "Custom Task", "type": "custom", "task": args.task}
        state = run_agent(meta["task"], max_iterations=args.max_iter, max_cost=args.max_cost)
        results = [state_to_report(state, meta)]
    elif args.task_id:
        meta = next((t for t in TEST_TASKS if t["id"] == args.task_id), None)
        if not meta:
            print(f"ERROR: task-id must be 1-{len(TEST_TASKS)}", file=sys.stderr)
            sys.exit(1)
        state = run_agent(meta["task"], max_iterations=10 if meta.get("max_cost") is None else None, max_cost=meta.get("max_cost"))
        results = [state_to_report(state, meta)]
    else:
        results = run_all_tasks()
        print_summary(results)

if __name__ == "__main__":
    main()