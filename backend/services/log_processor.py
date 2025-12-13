# backend/services/log_processor.py
import re
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional
import logging
import uuid

logger = logging.getLogger(__name__)

class LogProcessor:
    """Process and enrich logs"""
    
    LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL', 'FATAL']
    
    def __init__(self, groq_service=None):
        self.groq = groq_service
        self.error_patterns = self._load_error_patterns()
    
    async def process(self, raw_log: Dict[str, Any]) -> Dict[str, Any]:
        """Process a raw log entry"""
        processed = {
            'id': self._generate_log_id(),
            'timestamp': self._extract_timestamp(raw_log),
            'level': self._extract_log_level(raw_log),
            'message': self._extract_message(raw_log),
            'service': raw_log.get('service', 'unknown'),
            'source': raw_log.get('source', 'unknown'),
            'environment': raw_log.get('environment', 'production'),
            'host': raw_log.get('host', 'unknown'),
            'metadata': raw_log.get('metadata', {}),
            'error_type': None,
            'stack_trace': None,
            'ai_analysis': None
        }
        
        # Enhanced processing for errors
        if processed['level'] in ['ERROR', 'CRITICAL', 'FATAL']:
            processed['error_type'] = self._classify_error(processed['message'])
            processed['stack_trace'] = self._extract_stack_trace(raw_log)
            
            # AI analysis (only for errors to save API calls)
            if self.groq:
                try:
                    ai_analysis = await self.groq.analyze_log(processed)
                    processed['ai_analysis'] = ai_analysis
                except Exception as e:
                    logger.error(f"AI analysis failed: {e}")
        
        return processed
    
    def _generate_log_id(self) -> str:
        return uuid.uuid4().hex
    
    def _extract_timestamp(self, log: dict) -> datetime:
        ts = log.get('timestamp') or log.get('@timestamp')
        if ts:
            if isinstance(ts, str):
                return datetime.fromisoformat(ts.replace('Z', '+00:00'))
            return ts
        return datetime.utcnow()
    
    def _extract_log_level(self, log: dict) -> str:
        if 'level' in log:
            level = str(log['level']).upper()
            if level in self.LOG_LEVELS:
                return level
        
        message = str(log.get('message', '')).upper()
        for level in self.LOG_LEVELS:
            if level in message:
                return level
        
        return 'INFO'
    
    def _extract_message(self, log: dict) -> str:
        return str(log.get('message', log.get('msg', '')))
    
    def _classify_error(self, message: str) -> str:
        for pattern, error_type in self.error_patterns.items():
            if re.search(pattern, message, re.IGNORECASE):
                return error_type
        return 'UNKNOWN_ERROR'
    
    def _extract_stack_trace(self, log: dict) -> Optional[str]:
        message = str(log.get('message', ''))
        patterns = [
            r'Traceback \(most recent call last\):.*',
            r'at .*\(.*:\d+:\d+\)',
        ]
        for pattern in patterns:
            match = re.search(pattern, message, re.DOTALL)
            if match:
                return match.group(0)[:2000]
        return None
    
    def _load_error_patterns(self) -> dict:
        return {
            r'connection.*refused|ECONNREFUSED': 'CONNECTION_ERROR',
            r'timeout|timed out': 'TIMEOUT_ERROR',
            r'out of memory|oom': 'MEMORY_ERROR',
            r'database|db.*error': 'DATABASE_ERROR',
            r'permission|403|forbidden': 'PERMISSION_ERROR',
            r'404|not found': 'NOT_FOUND_ERROR',
            r'500|internal server': 'SERVER_ERROR',
            r'authentication|auth.*failed': 'AUTHENTICATION_ERROR',
        }
