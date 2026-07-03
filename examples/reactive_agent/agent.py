"""Reactive agent definition that queries the live-synced Chroma DB."""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Callable

import requests
from langchain_core.embeddings import Embeddings, FakeEmbeddings
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool

from pydebeziumai.adapters.chroma import ChromaAdapter
from pydebeziumai.retrieval import create_retriever_tool

# Configure Logging
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("reactive_agent")


def invoke_tool_safely(tool: BaseTool, query: str) -> str:
    """Safely invoke the tool supporting both dict and string input formats."""
    try:
        res = tool.invoke({"query": query})
        if isinstance(res, str) and res.strip():
            return res
    except Exception:
        pass

    try:
        res = tool.invoke(query)
        if isinstance(res, str):
            return res
    except Exception as e:
        return f"Error invoking retriever tool: {e}"

    return ""


def create_openai_agent(tool: BaseTool) -> Callable[[str], str] | None:
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
        logger.warning(f"Failed to load LangChain/OpenAI packages: {e}. Checking local alternatives...")
        return None


def create_ollama_agent(tool: BaseTool) -> tuple[Callable[[str], str], str] | None:
    """Try to create an agent using a local Ollama instance."""
    ollama_url = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    try:
        resp = requests.get(f"{ollama_url}/api/tags", timeout=2)
        if resp.status_code != 200:
            return None
        models_data = resp.json()
        models = [m["name"] for m in models_data.get("models", [])]
        if not models:
            return None

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
            tool_output = invoke_tool_safely(tool, user_query)
            context = "No matching items found in database." if not tool_output.strip() else tool_output

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
        return None


def create_mock_agent(tool: BaseTool) -> Callable[[str], str]:
    """Fallback mock agent that simulates LLM response based directly on retriever output."""

    def query_mock(user_query: str) -> str:
        tool_output = invoke_tool_safely(tool, user_query)
        if not tool_output.strip():
            return "Mock LLM: I searched the live catalog database but found no matching products."

        # Parse quantity and price from retrieved text to simulate smart decision
        lines = tool_output.split("\n")
        name = ""
        price = ""
        quantity = 0
        for line in lines:
            if line.startswith("Product:"):
                name = line.replace("Product:", "").strip()
            elif line.startswith("Price:"):
                price = line.replace("Price:", "").strip()
            elif line.startswith("Quantity:"):
                with contextlib.suppress(ValueError):
                    quantity = int(line.replace("Quantity:", "").strip())

        if quantity > 0:
            return f"Mock LLM: Yes! We have '{name}' in stock for {price} (current quantity: {quantity} available)."
        else:
            return f"Mock LLM: I found '{name}' in our catalog database, but it is currently out of stock."

    return query_mock


def get_agent(persist_dir: str) -> tuple[Callable[[str], str], str]:
    # 1. Initialize Embeddings
    embeddings: Embeddings
    try:
        from langchain_huggingface import HuggingFaceEmbeddings

        embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    except ImportError:
        embeddings = FakeEmbeddings(size=384)

    # 2. Configure Chroma Adapter
    adapter = ChromaAdapter(
        collection_name="reactive_catalog",
        embeddings=embeddings,
        persist_directory=persist_dir,
    )

    # 3. Create Retriever Tool using pydebeziumai helper
    retriever_tool = create_retriever_tool(
        adapter=adapter,
        name="query_inventory",
        description="Queries the inventory database catalog for products by name or category.",
    )

    # 4. Decide Agent Mode
    query_agent = create_openai_agent(retriever_tool)
    if query_agent:
        return query_agent, "OpenAI GPT-4o-mini"

    ollama_res = create_ollama_agent(retriever_tool)
    if ollama_res:
        return ollama_res

    return create_mock_agent(retriever_tool), "Local Mock Agent"
