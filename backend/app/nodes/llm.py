from langchain.chat_models import init_chat_model
from langchain_community.embeddings import DashScopeEmbeddings

from backend.app.services.config import settings

_llm = None
_embedding_model = None


def get_llm():
    global _llm
    if _llm is None:
        _llm = init_chat_model(
            model=settings.openai_model_id,
            model_provider="openai",
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            temperature=0.4,
        )
    return _llm


def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = DashScopeEmbeddings(model=settings.embedding_model_name)
    return _embedding_model


if __name__ == "__main__":
    get_llm()
    get_embedding_model()
