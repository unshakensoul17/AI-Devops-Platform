# backend/services/groq_service.py
from groq import AsyncGroq
from typing import Dict, Any, List
import logging
import json
from config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

class GroqAIService:
    def __init__(self):
        if not settings.GROQ_API_KEY:
            logger.warning("⚠️ Groq API key not set")
            self.client = None
        else:
            self.client = AsyncGroq(api_key=settings.GROQ_API_KEY)
            self.model = settings.GROQ_MODEL
    
    async def analyze_log(self, log: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze a single log entry"""
        if not self.client:
            return {"error": "Groq AI not configured"}
        
        try:
            prompt = f"""Analyze this log and provide JSON response:

Log Level: {log.get('level', 'UNKNOWN')}
Service: {log.get('service', 'unknown')}
Message: {log.get('message', '')}

Provide JSON with:
{{"error_type": "category", "severity": "LOW/MEDIUM/HIGH/CRITICAL", "summary": "one-line", "likely_cause": "cause", "quick_fix": "action"}}

Respond ONLY with valid JSON."""

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a DevOps expert. Respond with JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=settings.GROQ_TEMPERATURE,
                max_tokens=settings.GROQ_MAX_TOKENS,
            )
            
            content = response.choices[0].message.content.strip()
            
            # Clean markdown if present
            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]
                content = content.strip()
            
            return json.loads(content)
            
        except Exception as e:
            logger.error(f"❌ Groq analysis error: {e}")
            return {"error": str(e)}
    
    async def summarize_logs(self, logs: List[Dict], max_logs: int = 30) -> str:
        """Summarize multiple logs"""
        if not self.client:
            return "Groq AI not configured"
        
        try:
            log_samples = logs[:max_logs]
            log_text = "\n".join([
                f"[{log.get('level')}] {log.get('service')}: {log.get('message', '')[:100]}"
                for log in log_samples
            ])
            
            prompt = f"""Analyze these logs and provide summary:

{log_text}

Provide:
1. System health status
2. Key issues (top 3)
3. Critical errors
4. Recommended actions

Keep under 200 words."""

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a DevOps expert."},
                    {"role": "user", "content": prompt}
                ],
                temperature=settings.GROQ_TEMPERATURE,
                max_tokens=400,
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"❌ Summarization error: {e}")
            return f"Error: {str(e)}"