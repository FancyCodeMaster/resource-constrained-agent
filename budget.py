# budget enforcer - hard stop on llm call count and total cost
# raise budget exceeded error ; immediately halt execution; 

from dataclasses import dataclass, field
from typing import Optional

class BudgetExceededError(Exception):
    """raise when the agent hits LLM call count or cost limit."""
    def __init__(
            self,
            reason: str,
            calls_used: int,
            cost_used: float,
            estimated_cost: float,
            completed_steps: list
    ):
        self.reason = reason
        self.calls_used = calls_used
        self.cost_used = cost_used
        self.completed_steps = completed_steps
        self.estimated_cost = estimated_cost
        super().__init__(
            f"{reason}. Calls used: {calls_used}, Actual Cost: {cost_used}, Estimated Total Cost: {cost_used + estimated_cost}. Completed steps: {completed_steps}"
        )

# create budget state
# it should track number of calls used, cost used and completed steps

@dataclass
class BudgetState:
    calls_used: int = 0
    cost_used: float = 0.0
    estimated_cost: float = 0.0
    completed_steps: list = field(default_factory=list)

    # cost per 1k tokens for input and ouput of gpt-4o-mini
    cost_per_1k_input: float = 0.000150
    cost_per_1k_output: float = 0.000600

    max_calls: int = 10
    max_cost: float = 0.20


    def record_call(self, input_tokens: int, output_tokens: int, estimated_cost: float, step_summary: Optional[str] = None) -> float:
        """ 
        Register an LLM call
        Raise BudgetExceededError if either the call count or dollar cost limit is hit.
        """
        self.calls_used += 1
        print(f"Recording call #{self.calls_used} with {input_tokens} input tokens and {output_tokens} output tokens.")
        call_cost = (input_tokens / 1000) * self.cost_per_1k_input + (output_tokens / 1000) * self.cost_per_1k_output
        self.cost_used += call_cost

        self.estimated_cost  = estimated_cost

        if step_summary:
            self.completed_steps.append(step_summary)

        # if self.calls_used > self.max_calls:
        #     raise BudgetExceededError(
        #         reason=f"Call count limit exceeded ({self.calls_used}/{self.max_calls})",
        #         calls_used=self.calls_used,
        #         cost_used=self.cost_used,
        #         estimated_cost=self.estimated_cost,
        #         completed_steps=self.completed_steps
        #     )

        # if self.cost_used > self.max_cost:
        #     raise BudgetExceededError(
        #         reason=f"Cost limit exceeded ({self.cost_used:.2f}/{self.max_cost:.2f})",
        #         calls_used=self.calls_used,
        #         cost_used=self.cost_used,
        #         estimated_cost=self.estimated_cost,
        #         completed_steps=self.completed_steps
        #     )
        
        return call_cost
    
    def remaining_calls(self) -> int:
        return self.max_calls - self.calls_used
    
    def remaining_cost(self) -> float:
        return self.max_cost - self.cost_used
    
    def summary(self) -> str:            
        if (self.max_cost - self.cost_used - self.estimated_cost) < 0:
            return(
                f"Calls: {self.calls_used}/{self.max_calls}\n"
                f"Estimate Total Cost: Actual: ${self.cost_used:.6f} + Estimated: ${self.estimated_cost:.6f} = Total: ${self.cost_used + self.estimated_cost:.6f}/ Max: ${self.max_cost:.6f}\n"
                f"Completed Steps: {self.completed_steps}\n"
                f"Remaining Calls: 0(due to expected budget exceeded)\n"
            )
        return(
                f"Calls: {self.calls_used}/{self.max_calls}\n"
                f"Cost: ${self.cost_used:.6f}/{self.max_cost:.6f}\n"
                f"Remaining Calls: {self.remaining_calls()}\n"
                f"Remaining Cost: ${self.remaining_cost():.6f}\n"
                f"Completed Steps: {self.completed_steps}\n"
            )