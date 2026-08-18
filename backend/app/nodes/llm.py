from langchain.chat_models import init_chat_model
from langchain_community.embeddings import DashScopeEmbeddings

from backend.app.services.config import get_settings

llm=None
embedding_model=None

settings = get_settings()

def get_llm():
    global llm
    if llm is None:
        llm = init_chat_model(
            model=settings.openai_model_id,
            model_provider="openai",
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            temperature=0.4,
        )
    # print(f"""model: {get_settings().openai_model}
    #         base_url: {get_settings().openai_base_url}
    #         api_key: {get_settings().openai_api_key}""")
    return llm

def get_embedding_model():
    global embedding_model
    if embedding_model is None:
        embedding_model = DashScopeEmbeddings(model=settings.embedding_model_name)
        # print(f"Embedding model: {embedding_model}")
    return embedding_model

if __name__=="__main__":
    get_llm()
    get_embedding_model()
