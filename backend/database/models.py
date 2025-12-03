# backend/database/models.py
from sqlalchemy import Column, String, DateTime, Text, Integer, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime

Base = declarative_base()

class LogEntry(Base):
    __tablename__ = "logs"
    
    id = Column(String(16), primary_key=True)
    timestamp = Column(DateTime, index=True, nullable=False)
    level = Column(String(20), index=True, nullable=False)
    message = Column(Text, nullable=False)
    service = Column(String(100), index=True)
    source = Column(String(100))
    environment = Column(String(50), index=True)
    host = Column(String(255))
    error_type = Column(String(50), index=True)
    stack_trace = Column(Text)
    metadata = Column(JSONB)
    ai_analysis = Column(JSONB)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Full-text search index
    __table_args__ = (
        Index('idx_message_fulltext', 'message', postgresql_using='gin',
              postgresql_ops={'message': 'gin_trgm_ops'}),
    )