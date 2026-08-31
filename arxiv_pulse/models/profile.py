"""
Profile models - 检索领域档案
"""

import json

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint

from arxiv_pulse.models.base import Base, utcnow


class ResearchProfile(Base):
    __tablename__ = "research_profiles"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    retrieval_plan = Column(Text)  # JSON: {"arxiv_queries": [], "s2_query": "", "keywords": [], "exclude_words": []}
    journals = Column(Text)        # JSON: [{"key","name","issn","enabled"}]
    sources = Column(Text, default='{"arxiv": true, "crossref": true, "s2": true}')
    enabled = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def sources_json(self) -> dict:
        try:
            return json.loads(self.sources) if self.sources else {"arxiv": True, "crossref": True, "s2": True}
        except (ValueError, TypeError):
            return {"arxiv": True, "crossref": True, "s2": True}

    def to_dict(self):
        def _load(value, default):
            try:
                return json.loads(value) if value else default
            except (ValueError, TypeError):
                return default

        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "retrieval_plan": _load(self.retrieval_plan, {}),
            "journals": _load(self.journals, []),
            "sources": _load(self.sources, {"arxiv": True, "crossref": True, "s2": True}),
            "enabled": bool(self.enabled),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class PaperProfile(Base):
    __tablename__ = "paper_profiles"
    __table_args__ = (UniqueConstraint("profile_id", "paper_id"),)

    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, nullable=False, index=True)
    paper_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime, default=utcnow)
