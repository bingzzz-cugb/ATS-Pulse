import json
import logging
import re
import time
from typing import Any

from tqdm import tqdm

from arxiv_pulse.core import Config, Database
from arxiv_pulse.models import Paper
from arxiv_pulse.utils import output

logger = logging.getLogger(__name__)


class PaperSummarizer:
    def __init__(self):
        self.db = Database()
        self.config = Config

        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0

        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

        if self.config.AI_API_KEY:
            pass
        else:
            output.warn("AI API密钥未设置，使用基础总结")

    def extract_keywords(self, text: str, max_keywords: int = 10) -> list[str]:
        """Extract keywords from text, preserving common phrases"""
        common_phrases = [
            "deep learning",
            "machine learning",
            "neural network",
            "neural networks",
            "density functional",
            "density functional theory",
            "molecular dynamics",
            "quantum mechanics",
            "ab initio",
            "first principles",
            "force field",
            "force fields",
            "graph neural network",
            "convolutional neural network",
            "reinforcement learning",
            "transfer learning",
            "supervised learning",
            "unsupervised learning",
            "semi-supervised",
            "computational materials",
            "materials design",
            "high throughput",
            "structure prediction",
            "energy storage",
            "battery materials",
            "electronic structure",
            "band gap",
            "phase transition",
            "crystal structure",
            "atomistic simulation",
            "interatomic potential",
            "potential energy surface",
            "training data",
            "training set",
            "test set",
            "validation set",
            "feature engineering",
            "hyperparameter",
            "optimization algorithm",
            "gradient descent",
            "activation function",
            "loss function",
            "training process",
        ]

        text_lower = text.lower()
        found_phrases = []
        for phrase in common_phrases:
            if phrase in text_lower:
                found_phrases.append(phrase)

        single_words = re.findall(r"\b[A-Za-z][a-z]{4,}\b", text_lower)
        common_words = {
            "this",
            "that",
            "with",
            "from",
            "have",
            "which",
            "there",
            "their",
            "about",
            "using",
            "based",
            "approach",
            "method",
            "study",
            "paper",
            "research",
            "results",
            "show",
            "find",
            "found",
            "propose",
            "proposed",
            "however",
            "therefore",
            "furthermore",
            "moreover",
            "between",
            "through",
            "within",
            "without",
            "these",
            "those",
            "where",
            "when",
            "while",
        }

        word_freq = {}
        phrase_words = set()
        for phrase in found_phrases:
            phrase_words.update(phrase.split())

        for word in single_words:
            if word not in common_words and word not in phrase_words and len(word) > 4:
                word_freq[word] = word_freq.get(word, 0) + 1

        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        single_keywords = [word for word, _ in sorted_words[: max_keywords - len(found_phrases)]]

        return found_phrases + single_keywords

    def get_summary_prompt(self, paper: Paper, lang: str = "zh") -> tuple[str, str]:
        """Get summary prompt and system message based on language"""

        lang_names = {
            "zh": "Chinese",
            "en": "English",
            "ru": "Russian",
            "fr": "French",
            "de": "German",
            "es": "Spanish",
            "ar": "Arabic",
        }
        target_lang = lang_names.get(lang, "English")

        prompt = f"""
Please summarize the following research paper in a structured format. Write your response in {target_lang}.

Title: {paper.title}

Abstract: {paper.abstract}

Please provide:
1. Key findings/conclusions (bullet points, most important)
2. Methodology/approach used
3. Relevant keywords (5-10)

Please format your response as a JSON object with the following fields:
- key_findings: array of strings (bullet points of key findings and conclusions)
- methodology: string (brief description of the approach)
- keywords: array of relevant keywords (5-10)
"""
        system_msg = f"You are a research assistant specializing in summarizing physics and computational science papers. Write your response in {target_lang}."

        return prompt, system_msg

    def _fetch_full_text(self, paper: Paper) -> str | None:
        """只读本地全文缓存（手动上传 / AI 助手下载过的），无则返回 None——不执行网络下载"""
        try:
            from arxiv_pulse.models import PaperContentCache

            with self.db.get_session() as session:
                cache = session.query(PaperContentCache).filter_by(arxiv_id=paper.arxiv_id).first()
                if cache and cache.full_text:
                    return str(cache.full_text)
        except Exception:
            pass
        return None

    def _fetch_s2_abstract(self, paper: Paper) -> str | None:
        """从 Semantic Scholar 快速探测摘要（单次请求、短超时；拿到返回否则 None，立即降级不拖延）"""
        if not paper.doi:
            return None
        try:
            from arxiv_pulse.crawler.publisher import fetch_s2_abstract

            # retries=1 单次尝试，S2 限流/无记录时快速返回 None（不进入 AI 慢等待、不反复重试）
            abstract, _ = fetch_s2_abstract(paper.doi, retries=1)
            return abstract
        except Exception as e:
            output.warn(f"S2 摘要获取失败: {paper.arxiv_id}: {str(e)[:80]}")
            return None

    def _build_summary_prompt_from_text(self, paper: Paper, full_text: str, lang: str, is_abstract: bool = False) -> str:
        """基于全文/摘要（截断控制 token）构造总结 prompt"""
        target_lang = "Chinese" if lang == "zh" else "English"
        content = full_text[:12000]
        source_note = "summarized from abstract" if is_abstract else "summarized from full text"
        return f"""
Please summarize the following research paper in a structured format. Write your response in {target_lang}.

Title: {paper.title}

Abstract: Not available ({source_note})

Paper content (truncated):
{content}

Please provide:
1. Key findings/conclusions (bullet points, most important)
2. Methodology/approach used
3. Relevant keywords (5-10)

Please format your response as a JSON object with the following fields:
- key_findings: array of strings (bullet points of key findings and conclusions)
- methodology: string (brief description of the approach)
- keywords: array of relevant keywords (5-10)
"""

    def deepseek_summary(self, paper: Paper, progress_cb=None) -> str | None:
        """Generate summary using DeepSeek"""
        if not self.config.AI_API_KEY:
            return None

        prompt, system_msg = self.get_summary_prompt(paper, self.config.TRANSLATE_LANGUAGE)

        try:
            output.do(f"总结论文: {paper.arxiv_id}")
            if progress_cb:
                progress_cb("querying_abstract", "正在查询有无摘要...")

            # 摘要为空：不进入 AI 慢等待。
            # 1) 若手动上传过 PDF（PaperContentCache 缓存）→ 从缓存全文总结（内容来自用户，秒级读取）
            # 2) 否则快速探测 S2 摘要（单次请求），拿到则 write-back + AI 总结
            # 3) 都没有 → 秒级降级基础总结
            # 只有「有摘要或缓存全文」的论文才进入 AI 调用（最多 40s）；无摘要论文展开不会卡 90s。
            if not (paper.abstract or "").strip():
                full_text = self._fetch_full_text(paper)
                if full_text:
                    prompt = self._build_summary_prompt_from_text(
                        paper, full_text, self.config.TRANSLATE_LANGUAGE,
                    )
                    if progress_cb:
                        progress_cb("has_abstract", "已确认有摘要（本地全文），正在生成总结...")
                else:
                    s2_abstract = self._fetch_s2_abstract(paper)
                    if s2_abstract:
                        try:
                            self.db.update_paper(paper.arxiv_id, abstract=s2_abstract)
                            paper.abstract = s2_abstract
                        except Exception:
                            pass
                        prompt = self._build_summary_prompt_from_text(
                            paper, s2_abstract, self.config.TRANSLATE_LANGUAGE, is_abstract=True
                        )
                        output.info(f"S2 摘要素材: {len(s2_abstract)} 字符")
                        if progress_cb:
                            progress_cb("has_abstract", "已确认有摘要，正在生成总结...")
                    else:
                        output.info("S2 无摘要，跳过 AI 总结，直接基础总结")
                        if progress_cb:
                            progress_cb("no_abstract", "未找到摘要，已降级为基础总结")
                        return None
            elif progress_cb:
                # 论文本身有 abstract
                progress_cb("has_abstract", "已确认有摘要，正在生成总结...")

            if progress_cb:
                progress_cb("generating", "正在生成总结...")
            import openai

            client = openai.OpenAI(
                api_key=self.config.AI_API_KEY,
                base_url=self.config.AI_BASE_URL,
                timeout=40.0,
                max_retries=1,
            )

            response = client.chat.completions.create(
                model=self.config.AI_MODEL,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=self.config.SUMMARY_MAX_TOKENS,
                temperature=0.3,
                timeout=40.0,
            )

            if hasattr(response, "usage") and response.usage:
                usage = response.usage
                self.total_prompt_tokens += usage.prompt_tokens
                self.total_completion_tokens += usage.completion_tokens
                self.total_tokens += usage.total_tokens

                output.info(
                    f"Token 使用: 本次 提示 {usage.prompt_tokens}, 完成 {usage.completion_tokens}, 总计 {usage.total_tokens} | "
                    f"累计 提示 {self.total_prompt_tokens}, 完成 {self.total_completion_tokens}, 总计 {self.total_tokens}"
                )
            else:
                prompt_chars = len(prompt)
                estimated_tokens = prompt_chars // 4 + self.config.SUMMARY_MAX_TOKENS // 2
                self.total_tokens += estimated_tokens
                output.info(f"Token 使用: 估算约 {estimated_tokens} tokens | 累计总计 {self.total_tokens} tokens")

            result = response.choices[0].message.content

            def clean_json_response(text):
                """清理AI响应中的JSON代码块标记"""
                import re

                text = text.strip()
                json_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
                if json_match:
                    return json_match.group(1).strip()
                code_match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
                if code_match:
                    return code_match.group(1).strip()
                if text.startswith("```json"):
                    text = text[7:].strip()
                if text.startswith("```"):
                    text = text[3:].strip()
                if text.endswith("```"):
                    text = text[:-3].strip()
                return text

            cleaned_result = clean_json_response(result)

            try:
                summary_data = json.loads(cleaned_result)
            except json.JSONDecodeError:
                try:
                    summary_data = json.loads(result)
                except json.JSONDecodeError:
                    summary_data = {
                        "key_findings": [],
                        "methodology": "",
                        "keywords": self.extract_keywords(f"{paper.title} {paper.abstract}"),
                    }

            return json.dumps(summary_data)

        except Exception as e:
            output.error(f"DeepSeek API 错误: {paper.arxiv_id}", details={"exception": str(e)})
            return None

    def summarize_paper(self, paper: Paper, progress_cb=None) -> bool:
        """Summarize a single paper（无摘要则不生成，需上传 PDF）"""
        try:
            summary_json = None

            if self.config.AI_API_KEY:
                summary_json = self.deepseek_summary(paper, progress_cb=progress_cb)

            if not summary_json:
                # 基础总结已移除：无摘要时不生成总结（由前端提示上传 PDF）
                if progress_cb:
                    progress_cb("no_abstract", "未找到摘要，无法生成总结。请上传 PDF 后重试。")
                output.info(f"无摘要，放弃总结: {paper.arxiv_id}")
                return False

            if summary_json:
                try:
                    summary_data = json.loads(summary_json)
                    keywords = summary_data.get("keywords", [])
                except:
                    keywords = []

                success = self.db.update_paper(
                    paper.arxiv_id,
                    summarized=True,
                    summary=summary_json,
                    keywords=json.dumps(keywords),
                )

                if success:
                    output.done(f"总结完成: {paper.arxiv_id}")
                    return True

            return False

        except Exception as e:
            output.error(f"总结论文失败: {paper.arxiv_id}", details={"exception": str(e)})
            return False

    def summarize_pending_papers(self, limit: int = 20) -> dict[str, Any]:
        """Summarize papers that need summarization"""
        papers = self.db.get_papers_to_summarize(limit=limit)
        output.do(f"找到 {len(papers)} 篇需要总结的论文")

        successful = 0
        failed = 0

        for paper in tqdm(papers, desc="Summarizing papers"):
            if self.summarize_paper(paper):
                successful += 1
            else:
                failed += 1

            time.sleep(0.5)

        return {
            "total_processed": len(papers),
            "successful": successful,
            "failed": failed,
        }

    def get_summary_stats(self) -> dict[str, Any]:
        """Get summarization statistics"""
        with self.db.get_session() as session:
            total = session.query(Paper).count()
            summarized = session.query(Paper).filter_by(summarized=True).count()

            papers = session.query(Paper).filter_by(summarized=True).all()
            avg_summary_length = 0
            if papers:
                total_length = sum(len(p.summary or "") for p in papers)
                avg_summary_length = total_length / len(papers)

            return {
                "total_papers": total,
                "summarized_papers": summarized,
                "summarization_rate": summarized / total if total > 0 else 0,
                "avg_summary_length": avg_summary_length,
                "token_usage": {
                    "total_prompt_tokens": self.total_prompt_tokens,
                    "total_completion_tokens": self.total_completion_tokens,
                    "total_tokens": self.total_tokens,
                },
            }
