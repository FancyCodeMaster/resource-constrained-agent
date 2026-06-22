# Engineering Decisions

---

**Decision 1**

Initially, cost calculation relied on LLM usage output (input tokens, output tokens, and cost) after the API call. This could exceed the maximum budget because the cost was only known after execution.

To prevent this, I implemented a pre-request cost estimation approach:

- Calculate input token length from system + user prompts before the LLM call.
- Assume a maximum output token limit of 500 tokens.
- Estimate the total token usage and cost using the model's actual token pricing.
- Add the estimated cost to the already consumed cost.
- Allow the LLM call only if the estimated total remains within the configured budget.

I chose this approach because this acts as a strict cost guard, ensuring the total LLM expense never exceeds the maximum allowed budget.

---

**Decision 2**

I considered using Python's `multiprocessing` module with `Process.join(timeout=...)` to isolate code execution but chose `subprocess.run(..., timeout=timeout)` with a temporary file because subprocess gives us true OS-level process isolation (the sandboxed code cannot touch the parent's memory or globals), the temp-file approach produces accurate line-number tracebacks, and subprocess.TimeoutExpired is a specific, catchable exception — no bare `except` required.

---

**Decision 3**

I considered using a separate LLM call to parse tool arguments (letting the model output free-form text and then extracting the tool call with a second pass) but chose to enforce `response_format={"type": "json_object"}` on every ReAct call and require a strict `{"thought", "action", "action_input"}` schema because parsing failures in a 10-call budget would waste precious calls on retries, and structured output makes the dispatcher completely deterministic with no regex fragility.
