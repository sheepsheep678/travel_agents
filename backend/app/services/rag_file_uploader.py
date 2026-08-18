import glob
import hashlib
import os

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_community.vectorstores import SQLiteVec
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.app.nodes.llm import get_embedding_model
from backend.app.services.config import get_settings

settings = get_settings()

def load_file(path: str) -> list[Document]:
    """根据扩展名加载 txt / pdf"""
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
        print(f"[md5计算]文件{filepath}不存在")
        return

    if not os.path.isfile(filepath):
        print(f"[md5计算]路径{filepath}不是文件")
        return

    md5_obj = hashlib.md5()

    chunk_size = 4096  # 4KB分片，避免文件过大爆内存
    try:
        with open(filepath, "rb") as f:  # 必须二进制读取
            while chunk := f.read(chunk_size):
                md5_obj.update(chunk)

    except Exception as e:
        print(f"计算文件{filepath}md5失败, {str(e)}")
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
                print(f"跳过: {f}: 已在本地知识库中")
                continue
            print(f"加载: {f}")
            try:
                docs = load_file(f)
                all_docs.extend(splitter.split_documents(docs))
                pending_md5.append(md5_hex)
            except Exception as e:
                print(f"  跳过 {f}: {e}")

    print(f"共切分出 {len(all_docs)} 个 chunk")
    if not all_docs:
        print("没有新文档需要写入")
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
    print(f"写入完成 -> {settings.db_path}")
    return vec_store

if __name__ == "__main__":
    build_from_dir("./data")   # 把你的 txt/pdf 放这个目录