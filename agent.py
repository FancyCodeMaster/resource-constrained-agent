# ReAct Agent - Reasoning + Acting; planning loop with reflection and replanning.

"""
Loop structure per iteration:
1. Think - llm reasons about current state, picks a tool plus args
2. Act - Execute the chosen tool
3. Observe - Collect tool output
4. Reflect - Ask LLM "Am I making progress? (use a lightweight check prompt)
if stuck 2+ times in a row, trigger replan
5. Repeat or return Final Answer
"""

from dataclasses import dataclass, field
import json
import os
from typing import Any, Optional

from openai import OpenAI
import tiktoken
from dotenv import load_dotenv


from budget import BudgetExceededError, BudgetState
from tools.code_executor import execute_code
from tools.csv_analyzer import analyze_csv
from tools.web_search import web_search

load_dotenv()

MODEL_NAME = "gpt-4o-mini"
MAX_OUTPUT_TOKENS = 500

@dataclass
class Step:
    iteration: int
    thought: str
    action: str
    action_input: Any
    observation: str
    was_replanned: bool = False
    made_progress: Optional[bool] = None

@dataclass
class AgentState:
    task: str
    history: list[Step] = field(default_factory=list)
    budget: BudgetState = field(default_factory=BudgetState)
    stuck_count : int = 0
    final_answer: Optional[str] = None
    stopped_reason: Optional[str] = None

def log(msg: str):
    print(msg)


# System  prompts for ReAct, Reflection and Replanning

REACT_SYSTEM_PROMPT = """You are a precise, efficient AI agent with a strict resource budget.

## Your budget (CRITICAL):
- You have at most {max_calls} LLM calls total for this task (including this one).
- You have at most ${max_cost:.2f} total cost.
- Calls used so far: {calls_used}. Remaining: {remaining_calls}.

## Available tools:
1. web_search(query: str, max_results: int = 5)
   — Search the web via DuckDuckGo. Use for facts, current events, lookups.
2. execute_code(code: str)
   — Run Python code in a sandbox. Use for calculations, data processing.
3. analyze_csv(filepath: str)
   — Analyze a CSV file. Returns statistics, column info, sample rows.

## ReAct format — you MUST respond in this exact JSON format:
{{
  "thought": "<your reasoning about the current state and what to do next>",
  "action": "<web_search | execute_code | analyze_csv | final_answer>",
  "action_input": "<string argument for the tool, OR your final answer text>"
}}

## Rules:
- ALWAYS output valid JSON. Nothing outside the JSON block.
- If you have enough information to answer, use action="final_answer".
- Be concise — you have limited calls. Don't search for things you already know.
- If a tool returns an error or empty result, try a DIFFERENT approach, not the same call again.
- action_input for execute_code must be valid Python source code as a string.
- action_input for web_search must be a search query string.
- action_input for analyze_csv must be a file path string.
- action_input for final_answer must be your complete answer as a string.

## Current conversation history:
{history}
"""

REFLECT_SYSTEM_PROMPT = """You are evaluating whether an AI agent is making progress on a task.

Task: {task}

Last action taken: {action} with input: {action_input}
Result: {observation}

Previous stuck count: {stuck_count}

Respond ONLY with valid JSON:
{{"made_progress": true/false, "reason": "<one sentence>", "suggestion": "<if not progressing, what should the agent try instead?>"}}

made_progress = false if:
- The tool returned an error and retrying the same thing won't help
- The result was empty and a different query is needed
- The agent is clearly going in circles
- The tool result is irrelevant to the task
"""

REPLAN_SYSTEM_PROMPT = """You are helping an AI agent replan after getting stuck.

Task: {task}
Stuck count: {stuck_count}

History so far:
{history}

The agent has been stuck — its last {stuck_count} steps made no progress.
Suggest a completely DIFFERENT strategy. Respond in this exact JSON format:
{{
  "thought": "<analysis of why the agent got stuck and a different approach to try>",
  "action": "<web_search | execute_code | analyze_csv | final_answer>",
  "action_input": "<new approach argument>"
}}
"""

# history formatting
def format_history(steps: list[Step]) -> str:
    if not steps:
        return "No steps taken yet."
    lines = []
    for s in steps:
        lines.append(f"[Step {s.iteration}]")
        lines.append(f"  Thought: {s.thought}")
        lines.append(f"  Action: {s.action}({repr(s.action_input)})")
        lines.append(f"  Observation: {s.observation[:400]}")
        if s.was_replanned:
            lines.append("  *** REPLANNED ***")
        lines.append("")
    return "\n".join(lines)

# LLM call wrapper
def call_llm(client: OpenAI, system: str, user: str, budget: BudgetState, step_summary: str = "") -> dict:
    """
    Make one OpenAI chat completion call.
    Records token usage into BudgetState — raises BudgetExceededError if limits hit.
    Returns parsed JSON dict from the assistant's message.
    """

    # calculate estimated cost of this call 
    encoding = tiktoken.encoding_for_model(MODEL_NAME)
    input_tokens = len(encoding.encode(user+system))

    estimated_cost = (input_tokens / 1000) * budget.cost_per_1k_input + (MAX_OUTPUT_TOKENS / 1000) * budget.cost_per_1k_output
    log(f"Estimated cost of this call: ${estimated_cost:.6f}")

    budget.estimated_cost = estimated_cost
    

    if budget.calls_used >= budget.max_calls:
        log(f"Budget exceeded: {budget.calls_used}/{budget.max_calls} calls used")
        raise BudgetExceededError(
            reason=f"Call count limit exceeded ({budget.calls_used}/{budget.max_calls})",
            calls_used=budget.calls_used,
            cost_used=budget.cost_used,
            estimated_cost=estimated_cost,
            completed_steps=budget.completed_steps
        )
    
    if (budget.max_cost - budget.cost_used - estimated_cost) < 0:
        reason = f"Budget expected to exceed: Used: ${budget.cost_used:.6f} + Expected: ${estimated_cost:.6f} = Total: ${budget.cost_used + estimated_cost:.6f}/ Max: ${budget.max_cost:.6f} cost used."
        raise BudgetExceededError(
            reason=reason,
            calls_used=budget.calls_used,
            cost_used=budget.cost_used,
            estimated_cost=estimated_cost,
            completed_steps=budget.completed_steps
        )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0,
        response_format={"type": "json_object"},
        max_tokens=1000,
    )

    usage = response.usage
    budget.record_call(
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
        estimated_cost=estimated_cost,
        step_summary=step_summary or f"LLM call ({usage.prompt_tokens}in/{usage.completion_tokens}out tokens)",
    )
    log(f"LLM call used {usage.prompt_tokens} input tokens and {usage.completion_tokens} output tokens. Total cost so far: ${budget.cost_used:.6f}")

    content = response.choices[0].message.content
    return json.loads(content)

# tool dispatcher
def dispatch_tool(action: str, action_input: str) -> str:
    """Run the named tool and return a string observation."""
    if action == "web_search":
        result = web_search(action_input)
        if not result["success"]:
            return f"ERROR: {result['error']}"
        if not result["results"]:
            return "No results found for this query."
        lines = []
        for i, r in enumerate(result["results"], 1):
            lines.append(f"{i}. {r['title']}\n   {r['href']}\n   {r['body']}")
        return "\n\n".join(lines)

    elif action == "execute_code":
        result = execute_code(action_input)
        if not result["success"]:
            out = f"ERROR (exit {result['exit_code']}): {result['error']}"
            if result["stderr"]:
                out += f"\nStderr:\n{result['stderr']}"
            return out
        output = result["stdout"] or "(no output)"
        if result["stderr"]:
            output += f"\nStderr: {result['stderr']}"
        return output

    elif action == "analyze_csv":
        result = analyze_csv(action_input)
        if not result["success"]:
            return f"ERROR: {result['error']}"
        return json.dumps(result, indent=2)

    else:
        return f"Unknown tool: {action}"
    

# Main agent

MAX_ITERATIONS = 10

def run_agent(task: str, max_iterations: int = MAX_ITERATIONS, max_cost: float = None) -> AgentState:
    """
    Run the ReAct agent on a task.

    Returns AgentState with complete history, budget usage, and final answer.
    BudgetExceededError is caught here and stored in state.stopped_reason.
    """
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    state = None


    log(f"\n{'='*60}")
    log(f"TASK: {task}")
    log(f"{'='*60}")

    # using larger max iterations if max_cost is set just to showcase budget stop
    if max_iterations is None and max_cost is not None:
        estimated_cost_per_call = 0.0001 # rough estimate 
        max_iterations = int(max_cost / estimated_cost_per_call)
    elif max_iterations is None and max_cost is None:
        max_iterations = MAX_ITERATIONS
        max_cost = 0.20

    if max_cost is None:
        max_cost = 0.20


    state = AgentState(task=task, budget=BudgetState(max_cost=max_cost, max_calls=max_iterations))


    print(f"Starting agent with max_iterations={max_iterations} and max_cost={max_cost}")
    print(f"Initial budget state: {state.budget.summary()}")


    try:
        for iteration in range(1, max_iterations + 1):
            # get thought and action from LLM
            system_prompt = REACT_SYSTEM_PROMPT.format(
                max_calls=state.budget.max_calls,
                max_cost=state.budget.max_cost,
                calls_used=state.budget.calls_used,
                remaining_calls=state.budget.remaining_calls(),
                history=format_history(state.history)
            )
            
            react_response = call_llm(
                client=client,
                system=system_prompt,
                user=f"Task: {task}\n\n What is your next action?",
                budget=state.budget,
                step_summary=f"Step {iteration}: Think"
            )

            log(f"\n[Iteration {iteration}] | ReAct | {state.budget.summary()}")

            thought = react_response.get("thought", "")
            action = react_response.get("action", "")
            action_input = react_response.get("action_input", "")

            log(f"Thought: {thought}")
            log(f"Action: {action}({repr(str(action_input)[:100])})")

            # check final answer
            if action == "final_answer":
                state.final_answer = str(action_input)
                state.stopped_reason = "answer"
                state.history.append(Step(
                    iteration=iteration,
                    thought=thought,
                    action=action,
                    action_input=action_input,
                    observation="[Task complete]",
                    made_progress=True
                ))
                log(f"\nFINAL ANSWER: {state.final_answer}")
                break

            # dispatch the tool
            observation = dispatch_tool(action, str(action_input))
            log(f"Observation: {observation[:300]}")

            # reflect, did we make progress?
            reflect_system_prompt = REFLECT_SYSTEM_PROMPT.format(
                task=task,
                action=action,
                action_input=str(action_input)[:200],
                observation=observation[:400],
                stuck_count=state.stuck_count
            )

            reflect_response = call_llm(
                client=client,
                system=reflect_system_prompt,
                user="Evaluate progress.",
                budget=state.budget,
                step_summary=f"Step {iteration}: Reflect"
            )

            log(f"\n[Iteration {iteration}] | Reflection | {state.budget.summary()}")

            made_progress = reflect_response.get("made_progress", True)
            reflect_reason = reflect_response.get("reason", "")
            reflect_suggestion = reflect_response.get("suggestion", "")

            log(f"Progress: {made_progress} | Reason: {reflect_reason} | Suggestion: {reflect_suggestion}")

            was_replanned = False

            if not made_progress:
                state.stuck_count += 1
                log(f"Agent is stuck. Stuck count: {state.stuck_count}")
                log(f"Agent was stuck because: {reflect_reason}")
                log(f"Reflection suggestion: {reflect_suggestion}")

                if state.stuck_count >= 1:
                    log(f"Triggering replanning due to agent.")
                    replan_system_prompt = REPLAN_SYSTEM_PROMPT.format(
                        task=task,
                        stuck_count=state.stuck_count,
                        history=format_history(state.history)
                    )

                    replan_response = call_llm(
                        client=client,
                        system=replan_system_prompt,
                        user="Provide a new plan.",
                        budget=state.budget,
                        step_summary=f"Step {iteration}: Replan"
                    )

                    log(f"\n[Iteration {iteration}] | Replanning | {state.budget.summary()}")

                    # overwrite thought/action/input with the new plan
                    thought = replan_response.get("thought", thought)
                    action = replan_response.get("action", action)
                    action_input = replan_response.get("action_input", action_input)
                    was_replanned = True
                    state.stuck_count = 0
                    log(f"Replanned -> {action}({repr(str(action_input)[:100])}) ")

                    # executer replanned action
                    if action == "final_answer":
                        state.final_answer = str(action_input)
                        state.stopped_reason = "answer"
                        state.history.append(Step(
                            iteration=iteration,
                            thought=thought,
                            action=action,
                            action_input=action_input,
                            observation="[Task complete]",
                            was_replanned=was_replanned,
                            made_progress=True
                        ))
                        log(f"\nFINAL ANSWER: {state.final_answer}")
                        break

                    observation = dispatch_tool(action, str(action_input))
                    log(f"Replanned Observation: {observation[:300]}")

            else:
                state.stuck_count = 0

            state.history.append(Step(
                iteration=iteration,
                thought=thought,
                action=action,
                action_input=action_input,
                observation=observation,
                was_replanned=was_replanned,
                made_progress=made_progress
            ))
        else:
            state.stopped_reason = "max_iterations"
            log(f"\nStopped: reached max iterations ({max_iterations}) without a final answer.")

    except BudgetExceededError as bee:
        state.stopped_reason = "budget_exceeded"
        state.final_answer = None
        log(f"\n{bee}")
        log(f"Completed steps before budget exceeded: {bee.completed_steps}")

    log(f"\n{'='*60}")
    log(f"DONE | Reason: {state.stopped_reason} | {state.budget.summary()}")
    log(f"{'='*60}\n")

    return state
