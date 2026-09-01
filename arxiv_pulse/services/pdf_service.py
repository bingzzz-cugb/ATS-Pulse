"""
PDF service - 多源 PDF 下载缓存服务
"""

from pathlib import Path
from urllib.parse import quote

import requests

from arxiv_pulse.core import Config

_PDF_UA = {"User-Agent": "Mozilla/5.0"}

_UNPAYWALL_EMAIL = "cugb_bingz@qq.com"


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


def download_pdf_bytes(url: str, timeout: int = 60) -> bytes | None:
    """通用 PDF 下载（带 UA 伪装），失败返回 None"""
    try:
        resp = requests.get(url, timeout=timeout, headers=_PDF_UA)
        if resp.status_code == 200 and resp.content[:5] == b"%PDF-":
            return resp.content
        return None
    except requests.RequestException:
        return None


def resolve_pdf_source(paper) -> str | None:
    """解析论文的可下载 PDF 链接

    优先顺序：
    1. 已有可用 pdf_url（排除 api.elsevier.com / doi.org 死链接）
    2. Unpaywall OA 查询（按 DOI）
    3. arXiv 源兜底（直拼 arxiv.org/pdf）
    返回可下载 URL；无法解析返回 None
    """
    if paper.source == "arxiv":
        return f"https://arxiv.org/pdf/{paper.arxiv_id}.pdf"

    pdf_url = (paper.pdf_url or "").strip()
    if pdf_url and "api.elsevier.com" not in pdf_url and "doi.org/" not in pdf_url:
        return pdf_url

    if paper.doi:
        oa = lookup_oa_pdf(paper.doi)
        if oa:
            return oa

    return None


def lookup_oa_pdf(doi: str) -> str | None:
    """Unpaywall 查询 DOI 的合法开放获取 PDF 链接"""
    if not doi:
        return None
    url = f"https://api.unpaywall.org/v2/{quote(doi)}?email={_UNPAYWALL_EMAIL}"
    try:
        resp = requests.get(url, timeout=20, headers=_PDF_UA)
        if resp.status_code != 200:
            return None
        data = resp.json()
        oa = data.get("best_oa_location") or {}
        pdf = oa.get("url_for_pdf") or oa.get("url")
        return pdf if pdf else None
    except (requests.RequestException, ValueError):
        return None
