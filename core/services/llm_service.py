"""LangChain-based RAG service for generating answers."""

import logging

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from config import settings

logger = logging.getLogger(__name__)

# static system prompt to allow prompt caching
SYSTEM_PROMPT = """You are a helpful assistant that answers questions based on provided search results.

Instructions:
- Provide a clear, concise answer based on the search results
- If the sources conflict, mention the different perspectives
- If the information is insufficient, acknowledge limitations"""

# insert dynamic data to human prompt
HUMAN_PROMPT = """Query: {query}

Tavily Answer:
{tavily_answer}

Document Sources:
{contexts}

Please provide a comprehensive answer based on the above information."""


class LLMService:
    """LangChain-based RAG service for generating AI answers."""

    def __init__(self, model: str | None = None) -> None:
        """Initialize LLM service with specified model"""
        self._model_name = model or settings.openai_model
        self._llm = ChatOpenAI(
            model=self._model_name,
            api_key=settings.openai_api_key,
        )
        self._prompt = self._build_prompt()
        self._chain = self._prompt | self._llm | StrOutputParser()

    def _build_prompt(self) -> ChatPromptTemplate:
        return ChatPromptTemplate.from_messages(
            [
                ("system", SYSTEM_PROMPT),
                ("human", HUMAN_PROMPT),
            ]
        )

    async def generate_answer(
        self,
        query: str,
        tavily_answer: str,
        contexts: list[dict[str, str]],
    ) -> str:
        """Generate an answer based on Tavily's answer

        Arguments:
            query: The original user query
            tavily_answer: The answer provided by Tavily API (fallback)
            contexts: List of dicts with 'url', 'title', 'content' keys
        """
        # format the contexts as a string for the prompt
        formatted_contexts = "\n\n".join(
            [
                f"Source: {ctx.get('url', 'Unknown')}\n"
                f"Title: {ctx.get('title', 'Untitled')}\n"
                f"Content: {ctx.get('content', '')}"
                for ctx in contexts
            ]
        )

        return await self._chain.ainvoke(
            {
                "query": query,
                "tavily_answer": tavily_answer,
                "contexts": formatted_contexts,
            }
        )
