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