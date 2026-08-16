from langchain.chat_models import init_chat_model
from backend.app.services.config import get_settings

llm=None

def get_llm():
    global llm
    if llm is None:
        settings = get_settings()
        llm = init_chat_model(
            model=settings.openai_model,
            model_provider="openai",
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            temperature=0.8,
        )
    # print(f"""model: {get_settings().openai_model}
    #         base_url: {get_settings().openai_base_url}
    #         api_key: {get_settings().openai_api_key}""")
    return llm


if __name__=="__main__":
    get_llm()