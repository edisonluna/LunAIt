"""
Atlas — Microsoft Technical and Solutions Architect Agent
Uses the Anthropic SDK with Microsoft Learn tools to answer
architecture and infrastructure questions grounded in official
Microsoft documentation.
"""

import json
import os
import sys
from pathlib import Path

import anthropic
import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL = "claude-opus-4-6"
MAX_TOKENS = 8192
SYSTEM_PROMPT_FILE = Path(__file__).parent / "Atlas_Agent_Instructions.txt"

MS_LEARN_SEARCH_URL = "https://learn.microsoft.com/api/search"
MS_LEARN_SEARCH_API_VERSION = "2.0"

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "microsoft_docs_search",
        "description": (
            "Search the official Microsoft Learn documentation. "
            "Use this FIRST for every technical question involving Microsoft or Azure products. "
            "Returns a list of relevant documentation pages with titles, URLs, and descriptions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query for Microsoft documentation.",
                },
                "locale": {
                    "type": "string",
                    "description": "Locale for the search results (default: en-us).",
                    "default": "en-us",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "microsoft_docs_fetch",
        "description": (
            "Fetch the full content of a Microsoft Learn documentation page. "
            "Use AFTER microsoft_docs_search when you need full step-by-step procedures, "
            "complete architecture guidance, troubleshooting sections, or when the search "
            "excerpt was truncated. Always fetch before providing deployment commands, "
            "Bicep/ARM code, or multi-step configuration guidance."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The full URL of the Microsoft Learn page to fetch.",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "microsoft_code_sample_search",
        "description": (
            "Search for official Microsoft/Azure code samples. "
            "Use EVERY TIME you generate or reference Microsoft/Azure code. "
            "Run this BEFORE writing any code snippet — retrieve official samples first, "
            "then adapt to the user's scenario. Never write Azure CLI, PowerShell, Bicep, "
            "ARM, or SDK code from memory alone."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query for Microsoft/Azure code samples.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "delegate_to_atma",
        "description": (
            "Delegate a question to the ATM&A (Azure Tenant Management and Administration) agent. "
            "Use this when the request involves: existing Azure resources already deployed in a tenant, "
            "tenant-wide or subscription-wide governance and policy impact, RBAC/permissions on existing "
            "environments, operational impact or cost analysis of existing deployments, or 'what happens if', "
            "'where is', or 'how is this currently managed' questions about an existing tenant."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to delegate to the ATM&A agent.",
                },
                "context": {
                    "type": "string",
                    "description": "Any additional context or background for the ATM&A agent.",
                },
            },
            "required": ["question"],
        },
    },
]

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def microsoft_docs_search(query: str, locale: str = "en-us") -> str:
    """Search Microsoft Learn documentation."""
    params = {
        "api-version": MS_LEARN_SEARCH_API_VERSION,
        "search": query,
        "locale": locale,
        "$top": 10,
    }
    headers = {"Accept": "application/json"}

    try:
        response = requests.get(
            MS_LEARN_SEARCH_URL, params=params, headers=headers, timeout=15
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        return f"Error searching Microsoft documentation: {exc}"

    results = data.get("results", [])
    if not results:
        return "No official Microsoft documentation was found for this scenario."

    lines = [f"Microsoft Learn Search Results for: '{query}'\n"]
    for i, result in enumerate(results, 1):
        title = result.get("title", "Untitled")
        url = result.get("url", "")
        description = result.get("description", "No description available.")
        lines.append(f"{i}. **{title}**")
        lines.append(f"   URL: {url}")
        lines.append(f"   {description}\n")

    return "\n".join(lines)


def microsoft_docs_fetch(url: str) -> str:
    """Fetch and extract the main content from a Microsoft Learn documentation page."""
    if not url.startswith("https://learn.microsoft.com"):
        return "Error: Only official Microsoft Learn URLs (https://learn.microsoft.com) are permitted."

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Atlas-Agent/1.0)",
        "Accept": "text/html,application/xhtml+xml",
    }

    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        return f"Error fetching Microsoft documentation page: {exc}"

    soup = BeautifulSoup(response.text, "html.parser")

    # Remove navigation, scripts, and style elements
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    # Try to find the main article content
    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find(id="main-content")
        or soup.find(class_="content")
    )

    if main:
        text = main.get_text(separator="\n", strip=True)
    else:
        text = soup.get_text(separator="\n", strip=True)

    # Collapse excessive blank lines
    lines = [line for line in text.splitlines() if line.strip()]
    content = "\n".join(lines)

    # Truncate to avoid exceeding context limits
    max_chars = 8000
    if len(content) > max_chars:
        content = content[:max_chars] + f"\n\n[Content truncated. Full page: {url}]"

    return f"Content from {url}:\n\n{content}"


def microsoft_code_sample_search(query: str) -> str:
    """Search for official Microsoft/Azure code samples."""
    params = {
        "api-version": MS_LEARN_SEARCH_API_VERSION,
        "search": query,
        "locale": "en-us",
        "category": "Sample",
        "$top": 8,
    }
    headers = {"Accept": "application/json"}

    try:
        response = requests.get(
            MS_LEARN_SEARCH_URL, params=params, headers=headers, timeout=15
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        return f"Error searching Microsoft code samples: {exc}"

    results = data.get("results", [])
    if not results:
        # Fall back to a general search with "sample" appended
        return microsoft_docs_search(f"{query} code sample quickstart")

    lines = [f"Microsoft Official Code Samples for: '{query}'\n"]
    for i, result in enumerate(results, 1):
        title = result.get("title", "Untitled")
        url = result.get("url", "")
        description = result.get("description", "No description available.")
        lines.append(f"{i}. **{title}**")
        lines.append(f"   URL: {url}")
        lines.append(f"   {description}\n")

    return "\n".join(lines)


def delegate_to_atma(question: str, context: str = "") -> str:
    """Delegate a question about existing Azure resources to the ATM&A agent."""
    print(
        "\n[Atlas → ATM&A] Delegating to the Azure Tenant Management & Administration agent...\n"
    )
    delegation_message = (
        "This question involves existing Azure resources or tenant configuration and has been "
        "delegated to the ATM&A (Azure Tenant Management and Administration) agent, which has "
        "access to live tenant data and operational context.\n\n"
        f"Delegated question: {question}"
    )
    if context:
        delegation_message += f"\nContext: {context}"

    # In a full implementation, this would invoke the ATM&A agent via the Anthropic Agents API
    # or another agent orchestration mechanism. For now, return a stub response.
    return (
        delegation_message
        + "\n\n[ATM&A agent stub] This is a placeholder response. "
        "In production, the ATM&A agent would query your Azure tenant and return live results."
    )


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


def handle_tool_call(tool_name: str, tool_input: dict) -> str:
    """Route a tool call to the appropriate implementation."""
    if tool_name == "microsoft_docs_search":
        return microsoft_docs_search(**tool_input)
    elif tool_name == "microsoft_docs_fetch":
        return microsoft_docs_fetch(**tool_input)
    elif tool_name == "microsoft_code_sample_search":
        return microsoft_code_sample_search(**tool_input)
    elif tool_name == "delegate_to_atma":
        return delegate_to_atma(**tool_input)
    else:
        return f"Unknown tool: {tool_name}"


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------


def run_agentic_loop(client: anthropic.Anthropic, messages: list, system_prompt: str) -> None:
    """Run the Atlas agentic loop until a final response is produced."""
    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            tools=TOOLS,
            messages=messages,
        )

        # Append the assistant response to history
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            # Print the final text response
            for block in response.content:
                if hasattr(block, "text"):
                    print(f"\nAtlas: {block.text}\n")
            break

        elif response.stop_reason == "tool_use":
            # Process each tool call and collect results
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"  [Tool] {block.name}({json.dumps(block.input, ensure_ascii=False)[:120]}...)")
                    result = handle_tool_call(block.name, block.input)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )

            # Feed tool results back into the conversation
            messages.append({"role": "user", "content": tool_results})

        else:
            # Unexpected stop reason — surface any text and exit loop
            for block in response.content:
                if hasattr(block, "text"):
                    print(f"\nAtlas: {block.text}\n")
            break


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
            print("Session ended.")
            break

        messages.append({"role": "user", "content": user_input})

        try:
            run_agentic_loop(client, messages, system_prompt)
        except anthropic.APIError as exc:
            print(f"\n[Error] Anthropic API error: {exc}\n")
        except Exception as exc:
            print(f"\n[Error] Unexpected error: {exc}\n")


if __name__ == "__main__":
    main()
