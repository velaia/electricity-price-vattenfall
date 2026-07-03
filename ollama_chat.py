"""
Chat with Ollama (Gemma4) using tools from the MCP server.

Prerequisites:
  1. Start the MCP server:  uv run mcp_server.py
  2. Have Ollama running with gemma4:  ollama run gemma4

Usage:
  uv run ollama_chat.py
"""

import asyncio
import base64
from pathlib import Path

import ollama
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_SERVER_URL = "http://localhost:8000/mcp/"
OLLAMA_MODEL = "gemma4"
PROJECT_DIR = Path(__file__).parent.resolve()


def mcp_tools_to_ollama(mcp_tools) -> list[dict]:
    """Convert MCP tool definitions to Ollama's tool-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.inputSchema,
            },
        }
        for tool in mcp_tools.tools
    ]


def process_mcp_result(result) -> str:
    """Extract text from an MCP tool result. Save any images to disk."""
    parts = []
    for content in result.content:
        if content.type == "text":
            parts.append(content.text)
        elif content.type == "image":
            img_path = PROJECT_DIR / "mcp_result.png"
            img_path.write_bytes(base64.b64decode(content.data))
            parts.append(f"[Chart image saved to {img_path}]")
            print(f"  -> Image saved to {img_path}")
    return "\n".join(parts) if parts else "Done."


async def chat_loop(session: ClientSession, ollama_tools: list[dict]):
    """Main chat loop: user -> Ollama -> MCP tools -> Ollama -> response."""
    client = ollama.AsyncClient()
    messages = []

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break
        if not user_input or user_input.lower() in ("quit", "exit", "q"):
            break

        messages.append({"role": "user", "content": user_input})

        # Ask Ollama (with tool definitions)
        response = await client.chat(
            model=OLLAMA_MODEL,
            messages=messages,
            tools=ollama_tools,
        )

        # If Ollama wants to call tools, execute them via MCP
        while response.message.tool_calls:
            messages.append(response.message)

            for tool_call in response.message.tool_calls:
                name = tool_call.function.name
                args = tool_call.function.arguments
                print(f"  [Calling tool: {name}({args})]")

                result = await session.call_tool(name, args or {})
                tool_result = process_mcp_result(result)
                messages.append({"role": "tool", "content": tool_result})

            # Send tool results back to Ollama for a final answer
            response = await client.chat(
                model=OLLAMA_MODEL,
                messages=messages,
                tools=ollama_tools,
            )

        messages.append(response.message)
        print(f"\nGemma4: {response.message.content}")


async def main():
    print(f"Connecting to MCP server at {MCP_SERVER_URL} ...")

    async with streamablehttp_client(MCP_SERVER_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            mcp_tools = await session.list_tools()
            ollama_tools = mcp_tools_to_ollama(mcp_tools)

            tool_names = [t.name for t in mcp_tools.tools]
            print(f"Connected! Tools available: {tool_names}")
            print(f"Model: {OLLAMA_MODEL}")
            print("Type 'quit' to exit.\n")

            await chat_loop(session, ollama_tools)


if __name__ == "__main__":
    asyncio.run(main())
