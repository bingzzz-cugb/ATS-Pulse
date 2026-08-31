"""
PDF service - arXiv PDF 下载缓存服务
"""

from pathlib import Path

import requests

from arxiv_pulse.core import Config

_PDF_UA = {"User-Agent": "Mozilla/5.0"}


def pdf_cache_path(arxiv_id: str) -> Path:
    return Path(Config.DATA_DIR) / "pdfs" / f"{arxiv_id}.pdf"


def get_or_download_arxiv_pdf(arxiv_id: str) -> bytes | None:
    """返回缓存或新下载的 PDF 内容；失败返回 None（仅 arXiv 源）"""
    cache = pdf_cache_path(arxiv_id)
    if cache.exists():
        return cache.read_bytes()

    resp = requests.get(
        f"https://arxiv.org/pdf/{arxiv_id}.pdf",
        timeout=60,
        headers=_PDF_UA,
    )
    if resp.status_code != 200:
        return None

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(resp.content)
    return resp.content
