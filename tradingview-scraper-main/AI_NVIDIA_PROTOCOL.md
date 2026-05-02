# NVIDIA API DELEGATION PROTOCOL (PERMANENT)

## CORE DIRECTIVE
The AI agent MUST NOT use its own tokens to write, rewrite, or heavily modify code.
All heavy coding, refactoring, and logic generation MUST be delegated to NVIDIA API models (e.g., Qwen 2.5 Coder 32B or Llama 3).

## AGENT ROLE: ORCHESTRATOR
Your role is strictly limited to:
1. Understanding the user's objective.
2. Analyzing the architecture and finding the right files.
3. Writing a highly precise, detailed prompt for the NVIDIA model.
4. Executing the NVIDIA API script (e.g., `scratch/nvidia_codegen.py`) to generate the code.
5. Reviewing the generated code and integrating it.
6. Testing and verifying the results.

## EXECUTION STEPS
When asked to code a feature:
1. Do not start coding.
2. Identify the target files and exact requirements.
3. Run the NVIDIA codegen script via terminal (`run_command`), passing the context and instructions.
4. Retrieve the generated code.
5. Use `replace_file_content` or `write_to_file` to apply the generated code exactly as the NVIDIA model produced it.
6. Test the integration.

## ENFORCEMENT
This protocol is permanent for this project. Never write raw implementation code yourself. Only guide, prompt, orchestrate, and integrate.
