"""
FINN — Controller Finance Orchestration Agent
Claude API implementation based on FINN_CopilotStudio_Agent_Instructions.txt
"""

import os
import anthropic

INSTRUCTIONS_FILE = os.path.join(os.path.dirname(__file__), "FINN_CopilotStudio_Agent_Instructions.txt")
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096


def load_system_prompt() -> str:
    with open(INSTRUCTIONS_FILE, "r") as f:
        return f.read()


def run():
    system_prompt = load_system_prompt()
    client = anthropic.Anthropic()
    conversation: list[dict] = []

    print("FINN — Controller Finance Orchestration Agent")
    print("Type your question or 'exit' to quit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nSession ended.")
            break

        if user_input.lower() in ("exit", "quit"):
            print("Session ended.")
            break

        if not user_input:
            continue

        conversation.append({"role": "user", "content": user_input})

        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=conversation,
        )

        reply = response.content[0].text
        conversation.append({"role": "assistant", "content": reply})
        print(f"\nFINN: {reply}\n")


if __name__ == "__main__":
    run()
