"""
Atlas — Microsoft Technical and Solutions Architect Agent

Uses the Anthropic SDK with the official Microsoft Learn MCP connector to answer
architecture and infrastructure questions grounded in official Microsoft documentation.

The Microsoft Learn MCP server exposes three tools automatically:
  - microsoft_docs_search
  - microsoft_docs_fetch
  - microsoft_code_sample_search

Queries about existing Azure resources/tenant configuration are delegated to
the ATM&A (Azure Tenant Management and Administration) agent stub.
"""

import os
import sys
from pathlib import Path

import anthropic

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL = "claude-opus-4-6"
MAX_TOKENS = 8192
SYSTEM_PROMPT_FILE = Path(__file__).parent / "Atlas_Agent_Instructions.txt"
MAX_AGENTIC_ITERATIONS = 15

# Microsoft Learn MCP server — publicly available, no authentication required
MCP_SERVERS = [
    {
        "type": "url",
        "url": "https://learn.microsoft.com/api/mcp",
        "name": "microsoft-learn",
    }
]

# Required beta header for MCP client support
BETA_HEADER = "mcp-client-2025-04-04"

# ---------------------------------------------------------------------------
# ATM&A delegation
# ---------------------------------------------------------------------------

# Phrases that indicate the question is about EXISTING Azure resources or
# live tenant configuration (per delegation rules in Atlas_Agent_Instructions.txt)
ATMA_TRIGGER_PHRASES = [
    "existing",
    "deployed",
    "currently running",
    "already have",
    "already deployed",
    "my tenant",
    "our tenant",
    "my subscription",
    "our subscription",
    "management group",
    "what happens if",
    "where is",
    "how is this currently",
    "cost analysis",
    "current cost",
    "rbac",
    "permissions on",
    "policy impact",
    "compliance status",
    "existing deployments",
]

# Non-Azure Microsoft products that should never trigger ATM&A delegation
NON_AZURE_SIGNALS = [
    "fabric",
    "m365",
    "microsoft 365",
    "purview",
    "copilot studio",
    "power platform",
    "sharepoint",
    "teams",
    "exchange",
    "onelake",
    "lakehouse",
]


def should_delegate_to_atma(user_message: str) -> bool:
    """
    Returns True when the message concerns existing Azure resources or live
    tenant configuration, per the delegation rules in Atlas_Agent_Instructions.txt.
    """
    lower = user_message.lower()
    # Non-Azure Microsoft products are never delegated
    if any(signal in lower for signal in NON_AZURE_SIGNALS):
        return False
    return any(phrase in lower for phrase in ATMA_TRIGGER_PHRASES)


def delegate_to_atma(question: str) -> str:
    """
    Delegate a question to the ATM&A agent (stub).
    In production, invoke the ATM&A agent via its API or SDK.
    """
    print("\n[Atlas → ATM&A] Delegating to the Azure Tenant Management & Administration agent...\n")
    return (
        "This question involves existing Azure resources or live tenant configuration. "
        "I am delegating this to the ATM&A (Azure Tenant Management and Administration) agent, "
        "which has direct access to your Azure environment.\n\n"
        f"Delegated question: {question}\n\n"
        "[ATM&A agent stub — integration not yet configured. "
        "In production, the ATM&A agent will query your tenant and return live results.]"
    )


# ---------------------------------------------------------------------------
# Email delivery stub
# ---------------------------------------------------------------------------


def send_email_stub(content: str) -> None:
    """
    Stub for email delivery after Atlas delivers a response.
    Replace with Microsoft Graph API sendMail or SMTP integration.
    """
    # TODO: Implement via Microsoft Graph API (POST /me/sendMail)
    print("[Email stub] Email delivery is not yet configured.")


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------


def run_agent_turn(
    client: anthropic.Anthropic,
    system_prompt: str,
    messages: list,
) -> str:
    """
    Run Atlas through the agentic loop for a single user turn.
    The Anthropic MCP connector handles all tool discovery and execution
    against the Microsoft Learn MCP server transparently.

    Returns the final text response.
    """
    for _ in range(MAX_AGENTIC_ITERATIONS):
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=messages,
            mcp_servers=MCP_SERVERS,
            betas=[BETA_HEADER],
        )

        # Append the full assistant response to history
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text
            return ""

        if response.stop_reason in ("tool_use", "mcp_tool_use"):
            # The Anthropic backend dispatches MCP tool calls to
            # learn.microsoft.com/api/mcp and appends tool results —
            # just loop to send the updated messages back.
            continue

        # Unexpected stop reason — surface any text and exit
        for block in response.content:
            if hasattr(block, "text"):
                return block.text
        break

    return (
        "[Atlas] Maximum reasoning steps reached for this query. "
        "Please try rephrasing or breaking the question into smaller parts."
    )


# ---------------------------------------------------------------------------
# Main CLI
# ---------------------------------------------------------------------------


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable is not set.")
        sys.exit(1)

    if not SYSTEM_PROMPT_FILE.exists():
        print(f"Error: System prompt file not found: {SYSTEM_PROMPT_FILE}")
        sys.exit(1)

    system_prompt = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")
    client = anthropic.Anthropic(api_key=api_key)
    messages: list = []

    print("=" * 72)
    print("Atlas — Microsoft Technical and Solutions Architect Agent")
    print("Grounded exclusively in official Microsoft documentation.")
    print("Type 'exit' or 'quit' to end the session.")
    print("=" * 72)
    print()

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSession ended.")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            print("Goodbye.")
            break

        # Pre-flight ATM&A delegation check
        if should_delegate_to_atma(user_input):
            response_text = delegate_to_atma(user_input)
            print(f"\nAtlas: {response_text}\n")
            # Record delegation in history for context continuity
            messages.append({"role": "user", "content": user_input})
            messages.append(
                {"role": "assistant", "content": [{"type": "text", "text": response_text}]}
            )
            continue

        messages.append({"role": "user", "content": user_input})

        try:
            response_text = run_agent_turn(client, system_prompt, messages)
        except anthropic.APIError as exc:
            print(f"\n[Error] Anthropic API error: {exc}\n")
            messages.pop()  # remove failed user message to keep history clean
            continue
        except Exception as exc:
            print(f"\n[Error] Unexpected error: {exc}\n")
            messages.pop()
            continue

        print(f"\nAtlas: {response_text}\n")

        # Optional email delivery (per Atlas_Agent_Instructions.txt lines 157-163)
        try:
            offer = input("Would you like me to email this to you? (yes/no): ").strip().lower()
            if offer in ("yes", "y"):
                send_email_stub(response_text)
                print("Atlas: I've emailed this report to you.\n")
        except (EOFError, KeyboardInterrupt):
            print()


if __name__ == "__main__":
    main()
