from .router import RufloRouter
from .agents import TaskClassifier, PromptOptimizer, OutputValidator

print("[DEBUG] Agent System Starting...")

def run_trading_agent_system(user_input):
    router = RufloRouter()
    
    # 1. CLASSIFY
    print(f"[*] Classifying Task...")
    classification_response = router.execute(
        model_name="meta/llama-3.1-8b-instruct", # Fastest for classification
        prompt=user_input,
        system_prompt=TaskClassifier.get_system_prompt()
    )
    task_metadata = TaskClassifier.parse_response(classification_response)
    print(f"[+] Task metadata: {task_metadata}")

    # 2. SELECT MODEL (Ruflo Logic)
    selected_model = router.select_model(
        task_type=task_metadata["task_type"],
        complexity=task_metadata["complexity"],
        latency_priority=task_metadata["latency_priority"]
    )
    print(f"[*] Ruflo selected model: {selected_model}")

    # 3. OPTIMIZE PROMPT
    optimized_prompt = PromptOptimizer.optimize(task_metadata, user_input)
    print(f"[*] Prompt Optimized.")

    # 4. EXECUTE PRIMARY TASK
    print(f"[*] Executing via {selected_model}...")
    final_content = router.execute(
        model_name=selected_model,
        prompt=optimized_prompt,
        system_prompt="You are a senior Trading ML Engineer at Antigravity."
    )

    # 5. VALIDATE
    print(f"[*] Validating Output...")
    is_valid, reason = OutputValidator.validate(task_metadata["task_type"], final_content)
    
    if not is_valid:
        print(f"[!] Validation failed: {reason}. Regenerating...")
        # Simple one-time retry with correction hint
        final_content = router.execute(
            model_name=selected_model,
            prompt=f"Your previous answer was invalid: {reason}. Please fix and regenerate: {optimized_prompt}"
        )
    else:
        print(f"[+] Validation Passed.")

    # 6. FEEDBACK LOOP
    router.log_feedback(task_metadata["task_type"], selected_model, 1.0 if is_valid else 0.5)

    return final_content

if __name__ == "__main__":
    # Example Usage
    example_query = "Create a PyTorch module for detecting consolidation zones using a 1D CNN."
    result = run_trading_agent_system(example_query)
    print("\n--- FINAL RESPONSE ---\n")
    print(result)
