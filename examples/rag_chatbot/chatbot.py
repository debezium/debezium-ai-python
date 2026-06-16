"""Interactive RAG Chatbot querying the live-synced Chroma DB using LangGraph."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

import requests
from langchain_core.embeddings import Embeddings, FakeEmbeddings
from langchain_core.messages import HumanMessage
from langchain_core.tools import Tool

from pydebeziumai.adapters.chroma import ChromaAdapter

# Configure Logging
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("chatbot")


def create_openai_agent(tool: Tool) -> Callable[[str], str] | None:
    """Try to create an agent using OpenAI API."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from langchain_openai import ChatOpenAI
        from langgraph.prebuilt import create_react_agent

        model = ChatOpenAI(model_name="gpt-4o-mini", temperature=0)
        app = create_react_agent(model, [tool])

        def query_openai(user_query: str) -> str:
            state = {"messages": [HumanMessage(content=user_query)]}
            result = app.invoke(state)
            return str(result["messages"][-1].content)

        return query_openai
    except ImportError as e:
        print(f"Failed to load LangChain/OpenAI packages: {e}. Checking local alternatives...")
        return None


def create_ollama_agent(tool: Tool) -> tuple[Callable[[str], str], str] | None:
    """Try to create an agent using a local Ollama instance."""
    ollama_url = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    try:
        # Check if Ollama service is reachable
        resp = requests.get(f"{ollama_url}/api/tags", timeout=2)
        if resp.status_code != 200:
            return None
        models_data = resp.json()
        models = [m["name"] for m in models_data.get("models", [])]
        if not models:
            print("Local Ollama is running, but no models were found. Pull a model (e.g. 'ollama pull llama3').")
            return None

        # Choose model: check env override first, then preferred list, fallback to first available
        preferred = ["llama3.2", "gemma2", "llama3", "llama3.1", "qwen2.5"]
        selected_model = os.getenv("OLLAMA_MODEL")
        if not selected_model or selected_model not in models:
            for pref in preferred:
                matched = [m for m in models if m.startswith(pref)]
                if matched:
                    selected_model = matched[0]
                    break
        if not selected_model:
            selected_model = models[0]

        agent_mode = f"Local Ollama (using {selected_model})"

        def query_ollama(user_query: str) -> str:
            # 1. Retrieve relevant items
            tool_output = tool.invoke(user_query)
            context = "No matching items found in database." if not tool_output.strip() else tool_output

            # 2. Call Ollama Chat API
            payload = {
                "model": selected_model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a helpful inventory assistant. Answer the user's query "
                            "based on the following retrieved database records from our real-time "
                            "synchronized catalog:\n\n"
                            f"{context}\n\n"
                            "If the records do not contain the answer, politely state that you "
                            "could not find it."
                        ),
                    },
                    {"role": "user", "content": user_query},
                ],
                "stream": False,
            }
            try:
                api_resp = requests.post(f"{ollama_url}/api/chat", json=payload, timeout=120)
                if api_resp.status_code == 200:
                    return str(api_resp.json()["message"]["content"])
                else:
                    return f"Ollama Error (Status {api_resp.status_code}): {api_resp.text}"
            except Exception as ex:
                return f"Ollama API Connection Error: {ex}"

        return query_ollama, agent_mode
    except Exception:
        # Ollama not reachable
        return None


def create_mock_agent(tool: Tool) -> Callable[[str], str]:
    """Fallback agent simulating an LLM with direct retrieval output."""

    def query_mock(user_query: str) -> str:
        # Manually invoke our retriever tool to show the RAG data flow
        tool_output = tool.invoke(user_query)
        if not tool_output.strip():
            return "Mock LLM: I searched the live inventory database but found no matching products."

        return (
            f"Mock LLM: I found the following live database records matching '{user_query}':\n\n"
            f"{tool_output}\n\n"
            f"(Note: To use a real LLM, set the OPENAI_API_KEY environment variable or start local Ollama.)"
        )

    return query_mock


def main() -> None:
    print("=" * 70)
    print("PyDebeziumAI — Live RAG Chatbot (LangGraph)")
    print("=" * 70)

    # 1. Initialize Embeddings (matching stream_sync.py)
    embeddings: Embeddings
    try:
        from langchain_huggingface import HuggingFaceEmbeddings

        embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    except ImportError:
        embeddings = FakeEmbeddings(size=384)

    # 2. Configure Chroma Adapter
    persist_dir = os.path.join(os.path.dirname(__file__), "chroma_db")
    adapter = ChromaAdapter(
        collection_name="inventory_collection",
        embeddings=embeddings,
        persist_directory=persist_dir,
    )

    # 3. Create a Verbose Retriever Tool from Adapter
    retriever = adapter.as_retriever()

    def verbose_retrieve(query: str) -> str:
        print(f"\n[RAG Step] Searching Vector DB for: '{query}'...")
        docs = retriever.invoke(query)
        print(f"[RAG Step] Retrieved {len(docs)} matching document(s) from Vector DB:")
        for idx, doc in enumerate(docs, 1):
            print(f"  --- Document {idx} ---")
            print("  [Page Content]")
            for line in doc.page_content.splitlines():
                print(f"    {line}")
            print("  [Metadata]")
            print(f"    {doc.metadata}")
        print("-" * 50)

        # Format context for LLM
        formatted_docs = []
        for i, doc in enumerate(docs):
            op = doc.metadata.get("_op", "unknown")
            formatted_docs.append(f"Document {i + 1} (CDC Operation: {op}):\n{doc.page_content}")
        return "\n\n".join(formatted_docs)

    tool = Tool(
        name="query_inventory",
        description="Query this tool to fetch live product details (name, price, category, description) from the inventory database.",
        func=verbose_retrieve,
    )

    # 4. Decide Agent Mode (OpenAI vs. Local Ollama vs. Mock Fallback)
    agent_mode: str | None = None
    query_agent = create_openai_agent(tool)
    if query_agent:
        agent_mode = "OpenAI GPT-4o-mini"
        print("[Mode] Active LangGraph Agent (using OpenAI GPT-4o-mini)")
    else:
        ollama_res = create_ollama_agent(tool)
        if ollama_res:
            query_agent, agent_mode = ollama_res
            print(f"[Mode] Active Local LLM ({agent_mode})")
        else:
            query_agent = create_mock_agent(tool)
            agent_mode = "Local Mock Agent"
            print("[Mode] Local Mock Agent (Simulating LLM with direct retrieval tool)")

    print("\nChatbot is ready! Ask questions about the inventory (e.g. 'headphones', 'office chair', 'water bottle').")
    print("Type 'exit' or 'quit' to stop.\n")

    while True:
        try:
            user_input = input("You > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                print("Goodbye!")
                break

            assert query_agent is not None
            response = query_agent(user_input)
            print(f"\nAgent > {response}\n")
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}\n")


if __name__ == "__main__":
    main()
