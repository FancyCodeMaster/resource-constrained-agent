import gradio as gr
import os
import sys
import io
import threading
from contextlib import redirect_stdout

from main import TEST_TASKS, state_to_report
from agent import run_agent


def format_report(report: dict) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append("FINAL REPORT")
    lines.append("=" * 60)
    lines.append(f"Task ID     : {report['task_id']}")
    lines.append(f"Task Name   : {report['task_name']}")
    lines.append(f"Type        : {report['task_type']}")
    lines.append(f"Stopped     : {report['stopped_reason']}")
    lines.append(f"Steps Taken : {report['steps_taken']}")
    lines.append(f"Replans     : {report['replans']}")
    lines.append(f"Calls Used  : {report['calls_used']}")
    lines.append(f"Cost Used   : ${report['cost_used']:.6f}")
    lines.append("")
    lines.append("FINAL ANSWER:")
    lines.append("-" * 40)
    lines.append(str(report["final_answer"]) if report["final_answer"] else "(none)")
    lines.append("")
    lines.append("STEP HISTORY:")
    lines.append("-" * 40)
    for step in report["history_summary"]:
        progress = "✓" if step["made_progress"] else "✗"
        replan = " [REPLANNED]" if step["was_replanned"] else ""
        lines.append(f"  [{step['iteration']:>2}] {progress} {step['action']}{replan}")
    return "\n".join(lines)


def run_task(
    api_key: str,
    task_mode: str,
    task_id_str: str,
    custom_task: str,
    max_iter_str: str,
    max_cost_str: str,
):
    # --- Validate API key ---
    api_key = api_key.strip()
    if not api_key:
        yield "ERROR: Please enter your OpenAI API key.", ""
        return

    os.environ["OPENAI_API_KEY"] = api_key

    # --- Resolve task text and meta ---
    if task_mode == "Existing Task":
        try:
            task_id = int(task_id_str.split(":")[0].strip())
        except (ValueError, IndexError):
            yield "ERROR: Invalid task selection.", ""
            return
        meta = next((t for t in TEST_TASKS if t["id"] == task_id), None)
        if meta is None:
            yield "ERROR: Task not found.", ""
            return
        task_text = meta["task"]
        task_meta = meta
    else:
        task_text = (custom_task or "").strip()
        if not task_text:
            yield "ERROR: Please enter a custom task.", ""
            return
        task_meta = {"id": 0, "name": "Custom Task", "type": "custom", "task": task_text}

    # --- Parse max_iter ---
    max_iter = None
    if max_iter_str and max_iter_str.strip():
        try:
            max_iter = int(max_iter_str.strip())
            if max_iter <= 0:
                yield "ERROR: max_iter must be a positive integer.", ""
                return
        except ValueError:
            yield "ERROR: max_iter must be a positive integer.", ""
            return

    # --- Parse max_cost ---
    max_cost = None
    if max_cost_str and max_cost_str.strip():
        try:
            max_cost = float(max_cost_str.strip())
            if max_cost <= 0:
                yield "ERROR: max_cost must be a positive number.", ""
                return
        except ValueError:
            yield "ERROR: max_cost must be a positive number.", ""
            return

    # --- Override limits for preset tasks if not specified ---
    if task_mode == "Existing Task" and max_iter is None and max_cost is None:
        if meta.get("max_cost") is not None:
            max_cost = meta["max_cost"]
        else:
            max_iter = 10

    yield f"Running task: {task_meta['name']}\nTask: {task_text}\n\nPlease wait...", ""

    # --- Capture stdout for verbose output ---
    log_buffer = io.StringIO()
    result_holder = {}
    error_holder = {}

    def target():
        try:
            with redirect_stdout(log_buffer):
                state = run_agent(task_text, max_iterations=max_iter, max_cost=max_cost)
            result_holder["state"] = state
        except Exception as e:
            error_holder["error"] = str(e)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()

    import time
    while thread.is_alive():
        time.sleep(0.5)
        current_log = log_buffer.getvalue()
        yield current_log or "Running...", ""

    thread.join()

    if "error" in error_holder:
        yield f"ERROR during execution:\n{error_holder['error']}", ""
        return

    state = result_holder["state"]
    report = state_to_report(state, task_meta)
    verbose_log = log_buffer.getvalue()
    report_text = format_report(report)

    yield verbose_log or "(no verbose output)", report_text


# --- Task choices ---
TASK_CHOICES = [f"{t['id']}: {t['name']} [{t['type'].upper()}]" for t in TEST_TASKS]

with gr.Blocks(title="ReAct Agent Demo", theme=gr.themes.Soft()) as demo:
    gr.Markdown(
        """
        #Resource-Constrained ReAct Agent
        Run AI agent tasks with budget controls and real-time verbose output.
        """
    )

    with gr.Row():
        api_key_input = gr.Textbox(
            label="OpenAI API Key",
            placeholder="sk-...",
            type="password",
            scale=3,
        )

    gr.Markdown("---")
    gr.Markdown("### Task Configuration")

    with gr.Row():
        task_mode = gr.Radio(
            choices=["Existing Task", "Custom Task"],
            value="Existing Task",
            label="Task Mode",
        )

    with gr.Row(visible=True) as existing_row:
        task_id_dropdown = gr.Dropdown(
            choices=TASK_CHOICES,
            value=TASK_CHOICES[0],
            label="Select Task",
            scale=2,
        )

    with gr.Row(visible=False) as custom_row:
        custom_task_input = gr.Textbox(
            label="Custom Task",
            placeholder="Describe the task you want the agent to perform...",
            lines=3,
            scale=3,
        )

    with gr.Row():
        max_iter_input = gr.Textbox(
            label="Max Iterations (optional, positive integer)",
            placeholder="e.g. 10",
            scale=1,
        )
        max_cost_input = gr.Textbox(
            label="Max Cost in $ (optional, positive float)",
            placeholder="e.g. 0.05",
            scale=1,
        )

    run_btn = gr.Button("▶ Run Agent", variant="primary", size="lg")

    gr.Markdown("---")
    gr.Markdown("### Output")

    with gr.Row():
        verbose_output = gr.Textbox(
        label="Verbose Log",
        lines=20,
        max_lines=40,
        interactive=False,
    )

    report_output = gr.Textbox(
        label="Final Report",
        lines=20,
        max_lines=40,
        interactive=False,
    )

    # --- Toggle visibility based on task mode ---
    def toggle_mode(mode):
        return gr.update(visible=(mode == "Existing Task")), gr.update(visible=(mode == "Custom Task"))

    task_mode.change(toggle_mode, inputs=task_mode, outputs=[existing_row, custom_row])

    # --- Run ---
    run_btn.click(
        fn=run_task,
        inputs=[
            api_key_input,
            task_mode,
            task_id_dropdown,
            custom_task_input,
            max_iter_input,
            max_cost_input,
        ],
        outputs=[verbose_output, report_output],
    )

if __name__ == "__main__":
    demo.launch(share=False)