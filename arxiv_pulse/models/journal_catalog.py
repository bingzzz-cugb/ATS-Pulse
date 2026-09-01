"""
Crossref 期刊目录模型 - 全量期刊供检索档案的期刊组选择
"""

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from arxiv_pulse.models.base import Base, utcnow


class CrossrefJournal(Base):
    __tablename__ = "crossref_journals"

    id = Column(Integer, primary_key=True)
    issn = Column(String(40), nullable=False, unique=True)
    title = Column(Text)
    publisher = Column(String(200))
    acronym = Column(String(100), index=True)  # 标题显著词首字母缩写，如 Remote Sensing of Environment → RSE
    quartile = Column(String(4))  # SJR 分区 Q1/Q2（当前清单只收录二区以上）
    sjr = Column(Float)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
