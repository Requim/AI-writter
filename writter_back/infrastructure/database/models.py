"""SQLAlchemy数据库模型"""
from sqlalchemy import (
    Column, String, Text, DateTime, Integer, Boolean, Float,
    ForeignKey, JSON, UUID as SQLUUID
)
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.dialects.postgresql import JSONB, UUID
from datetime import datetime
from uuid import uuid4


class Base(DeclarativeBase):
    """基类"""
    pass


class NovelModel(Base):
    """小说表模型"""
    __tablename__ = "novels"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    novel_type = Column(String(50), nullable=False)
    title = Column(String(255), nullable=True)
    summary = Column(Text, nullable=True)
    total_outline = Column(JSONB, nullable=True)
    progress = Column(JSONB, nullable=True)
    status = Column(String(20), default="draft")
    thread_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    chapters = relationship("ChapterModel", back_populates="novel", cascade="all, delete-orphan")
    memories = relationship("MemoryModel", back_populates="novel", cascade="all, delete-orphan")


class ChapterModel(Base):
    """章节表模型"""
    __tablename__ = "chapters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id = Column(UUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    chapter_index = Column(Integer, nullable=False)
    title = Column(String(255), nullable=True)
    outline = Column(JSONB, nullable=True)
    content = Column(Text, nullable=True)
    word_count = Column(Integer, default=0)
    reflection_issues = Column(JSONB, nullable=True)
    user_decision = Column(JSONB, nullable=True)
    revision_count = Column(Integer, default=0)
    revision_history = Column(JSONB, nullable=True)
    status = Column(String(20), default="draft")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    novel = relationship("NovelModel", back_populates="chapters")


class MemoryModel(Base):
    """长期记忆表模型（向量存储）"""
    __tablename__ = "novel_memories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id = Column(UUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Text, nullable=True)  # 向量存储为JSON字符串（实际使用pgvector类型）
    meta_data = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    novel = relationship("NovelModel", back_populates="memories")
