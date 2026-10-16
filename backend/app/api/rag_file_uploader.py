import glob
import hashlib
import logging
import os

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.app.services.config import settings
from backend.app.services.rag_component import get_vector_store

logger = logging.getLogger(__name__)

# langchain-chroma 的 add_texts 不切批，会把整批文本一次性交给
# DashScopeEmbeddings.embed_documents（单次 HTTP 请求）；保守分批更稳，失败时也能定位批次。
INGEST_BATCH_SIZE = 10


def _collection_is_empty() -> bool:
    """集合内一个向量都没有则返回 True。

    md5.text 账本只按「源文件内容」去重，与向量库状态无关。向量库被删除（本次迁移、
    或误删 chroma_dir）时账本里仍记着全部 11 个文件，直接跳过会导致「一条都没入库」
    且不报错。这里识别这种不一致并强制全量重建。
    """
    try:
        return len(get_vector_store().get(limit=1)["ids"]) == 0
    except Exception as e:  # 目录不存在 / 客户端异常：按空库处理，触发全量入库
        logger.warning("读取 Chroma 集合状态失败，按空库处理: %s", e)
        return True


def load_file(path: str) -> list[Document]:
    """根据扩展名加载 txt / pdf；不支持的类型返回 None"""
    if path.lower().endswith(".pdf"):
        return PyPDFLoader(path).load()
    elif path.lower().endswith(".txt"):
        return TextLoader(path, encoding="utf-8").load()
    else:
        return None


def check_md5_hex(md5_for_check: str):
    if not os.path.exists(settings.md5_path):
        # 创建文件
        open(settings.md5_path, "w", encoding="utf-8").close()
        return False
    # md5 没处理过
    with open(settings.md5_path, "r", encoding="utf-8") as f:
        return md5_for_check in {line.strip() for line in f if line.strip()}


def save_md5_hex(md5_for_check: str):
    with open(settings.md5_path, "a", encoding="utf-8") as f:
        f.write(md5_for_check + "\n")


def get_file_md5_hex(filepath: str):  # 获取文件的md5的十六进制字符串
    if not os.path.exists(filepath):
        logger.warning("[md5计算]文件%s不存在", filepath)
        return

    if not os.path.isfile(filepath):
        logger.warning("[md5计算]路径%s不是文件", filepath)
        return

    md5_obj = hashlib.md5()

    chunk_size = 4096  # 4KB分片，避免文件过大爆内存
    try:
        with open(filepath, "rb") as f:  # 必须二进制读取
            while chunk := f.read(chunk_size):
                md5_obj.update(chunk)
    except Exception as e:
        logger.error("计算文件%s的md5失败: %s", filepath, e)
        return None

    md5_hex = md5_obj.hexdigest()
    return md5_hex


def build_from_dir(docs_dir: str):
    """遍历目录，加载并切分所有 txt/pdf 文档"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        separators=["\n\n", "\n", "。", "！", "？", "，", " "],
    )
    all_docs = []
    pending_md5 = []
    force_rebuild = _collection_is_empty()
    if force_rebuild:
        logger.warning("Chroma 集合为空或不可读，忽略 MD5 账本，执行全量入库")
    for f in glob.glob(os.path.join(docs_dir, "**/*"), recursive=True):
        if os.path.isfile(f) and f.lower().endswith((".txt", ".pdf")):
            md5_hex = get_file_md5_hex(f)
            if not force_rebuild and check_md5_hex(md5_hex):
                logger.info("跳过: %s: 已在本地知识库中", f)
                continue
            # 城市 = 文件名（不含扩展名），例如 北京.txt → 北京
            city = os.path.splitext(os.path.basename(f))[0]
            logger.info("加载: %s (城市: %s)", f, city)
            try:
                docs = load_file(f)
                if not docs:
                    continue
                for d in docs:
                    d.metadata["city"] = city
                # split_documents 会把 metadata 继承给每个 chunk
                all_docs.extend(splitter.split_documents(docs))
                pending_md5.append(md5_hex)
            except Exception as e:
                logger.warning("跳过 %s: %s", f, e)

    logger.info("共切分出 %d 个 chunk", len(all_docs))
    if not all_docs:
        logger.info("没有新文档需要写入")
        return None

    # 2. 写入 Chroma 向量库（集合配置与嵌入模型由 get_vector_store 统一提供）
    vec_store = get_vector_store()
    for start in range(0, len(all_docs), INGEST_BATCH_SIZE):
        batch = all_docs[start: start + INGEST_BATCH_SIZE]
        vec_store.add_documents(batch)
        logger.info("已写入 %d/%d 个 chunk",
                    min(start + INGEST_BATCH_SIZE, len(all_docs)), len(all_docs))
    for md5 in pending_md5:
        save_md5_hex(md5)
    logger.info("写入完成 -> %s（集合 %s，共 %d 个 chunk）",
                settings.chroma_dir, settings.collection, len(all_docs))
    return vec_store


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # 用脚本自身位置定位 data 目录，避免相对路径依赖当前工作目录(CWD)
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    build_from_dir(data_dir)   # 把你的 txt/pdf 放这个目录
