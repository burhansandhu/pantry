import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_groq import ChatGroq

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def get_llm(temperature=0.2):
    if not os.getenv("GROQ_API_KEY"):
        raise RuntimeError("Set GROQ_API_KEY in the root .env file.")
    return ChatGroq(
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        temperature=temperature,
        timeout=60,
        max_retries=1,
    )
