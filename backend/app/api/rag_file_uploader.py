import glob
import hashlib
import logging
import os

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_community.vectorstores import SQLiteVec
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.app.nodes.llm import get_embedding_model
from backend.app.services.config import settings

logger = logging.getLogger(__name__)


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
    for f in glob.glob(os.path.join(docs_dir, "**/*"), recursive=True):
        if os.path.isfile(f) and f.lower().endswith((".txt", ".pdf")):
            md5_hex = get_file_md5_hex(f)
            if check_md5_hex(md5_hex):
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

    # 2. 写入 SQLiteVec 向量库（自动建表 + 自动嵌入）
    vec_store = SQLiteVec.from_documents(
        documents=all_docs,
        embedding=get_embedding_model(),
        table=settings.table,
        db_file=settings.db_path,
    )
    for md5 in pending_md5:
        save_md5_hex(md5)
    logger.info("写入完成 -> %s", settings.db_path)
    return vec_store


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # 用脚本自身位置定位 data 目录，避免相对路径依赖当前工作目录(CWD)
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    build_from_dir(data_dir)   # 把你的 txt/pdf 放这个目录
