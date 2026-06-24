import os
import numpy as np
from pathlib import Path
from typing import Union, List

from sentence_transformers import SentenceTransformer

RAG_DIR = Path(__file__).parent
DATA_DIR = RAG_DIR / 'data'
DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR = DATA_DIR / 'uploads'
UPLOAD_DIR.mkdir(exist_ok=True)

os.environ['HF_HUB_DISABLE_SYMLINKS'] = '1'

MODEL_PATH = str(RAG_DIR / 'models' / 'bge-m3')
_model = None

def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(
            MODEL_PATH,
            trust_remote_code=True,
        )
    return _model

def get_text_embedding(text: str) -> np.ndarray:
    model = get_model()
    return model.encode(text, normalize_embeddings=True).astype(np.float32)

def get_text_embeddings(texts: List[str]) -> np.ndarray:
    model = get_model()
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=False).astype(np.float32)

def get_image_embedding(image_path: Union[str, Path]) -> np.ndarray:
    return get_text_embedding(f"[Image Description] {Path(image_path).name}")

def get_image_embeddings(image_paths: List[Union[str, Path]]) -> np.ndarray:
    texts = [f"[Image Description] {Path(p).name}" for p in image_paths]
    return get_text_embeddings(texts)

def get_embedding_dim() -> int:
    return 1024


def extract_text_from_file(file_path: Union[str, Path]) -> str:
    file_path = Path(file_path)
    ext = file_path.suffix.lower()
    if ext == '.txt':
        return file_path.read_text('utf-8', errors='ignore')
    elif ext == '.md':
        return file_path.read_text('utf-8', errors='ignore')
    elif ext == '.json':
        import json as j
        data = j.loads(file_path.read_text('utf-8', errors='ignore'))
        if isinstance(data, dict):
            return j.dumps(data, ensure_ascii=False)
        return str(data)
    elif ext in ('.py', '.js', '.ts', '.html', '.css', '.sql', '.yaml', '.yml', '.xml'):
        return file_path.read_text('utf-8', errors='ignore')
    elif ext in ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'):
        return f"[Image] {file_path.name}"
    elif ext == '.pdf':
        try:
            import PyPDF2
            text = []
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text.append(page.extract_text())
            return '\n'.join(text)
        except ImportError:
            return f"[PDF] {file_path.name}"
    else:
        try:
            return file_path.read_text('utf-8', errors='ignore')
        except:
            return f"[File] {file_path.name}"


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start = end - overlap
    return chunks or [text]