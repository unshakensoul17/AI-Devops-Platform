# backend/services/groq_service.py
from groq import AsyncGroq
from typing import List, Dict, Any, Optional
import logging
import json
from config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

class GroqAIService:
    """Groq AI service for log analysis"""
    
    def __init__(self):
        if not settings.GROQ_API_KEY:
            logger.warning("⚠ Groq API key not set - AI features will be disabled")
            self.client = None
        else:
            self.client = AsyncGroq(api_key=settings.GROQ_API_KEY)
            self.model = settings.GROQ_MODEL
            logger.info(f"✓ Initialized Groq AI with model: {self.model}")
    
    async def analyze_log(self, log: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze a single log entry"""
        if not self.client:
            return {"error": "Groq AI not configured"}
        
        try:
            prompt = f"""Analyze this log entry and provide structured insights:

Log Level: {log.get('level', 'UNKNOWN')}
Service: {log.get('service', 'unknown')}
Message: {log.get('message', '')}
Timestamp: {log.get('timestamp', '')}

Provide a JSON response with:
1. "error_type": category of error (DATABASE, NETWORK, AUTH, MEMORY, etc.)
2. "severity": LOW, MEDIUM, HIGH, or CRITICAL
3. "summary": one-line explanation
4. "likely_cause": probable root cause
5. "impact": potential system impact
6. "quick_fix": immediate action to take

Respond ONLY with valid JSON, no markdown."""

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert DevOps engineer analyzing application logs. Always respond with valid JSON only."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=settings.GROQ_TEMPERATURE,
                max_tokens=settings.GROQ_MAX_TOKENS,
            )
            
            # Parse JSON response
            content = response.choices[0].message.content.strip()
            
            # Remove markdown code blocks if present
            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]
                content = content.strip()
            
            analysis = json.loads(content)
            return analysis
            
        except json.JSONDecodeError as e:
            logger.error(f"✗ Failed to parse Groq response as JSON: {e}")
            return {"error": "Invalid JSON response from AI"}
        except Exception as e:
            logger.error(f"✗ Error analyzing log with Groq: {e}")
            return {"error": str(e)}
    
    async def summarize_logs(
        self,
        logs: List[Dict[str, Any]],
        max_logs: int = 50
    ) -> str:
        """Generate summary of multiple logs"""
        if not self.client:
            return "Groq AI not configured"
        
        try:
            # Sample logs if too many
            log_samples = logs[:max_logs]
            
            # Create concise log representation
            log_text = "\n".join([
                f"[{log.get('level', 'INFO')}] {log.get('timestamp', '')} - "
                f"{log.get('service', 'unknown')}: {log.get('message', '')[:100]}"
                for log in log_samples
            ])
            
            prompt = f"""Analyze these {len(log_samples)} application logs and provide a concise summary:

{log_text}

Provide:
1. Overall system health status
2. Key issues or patterns (top 3)
3. Most critical errors
4. Recommended immediate actions

Keep summary under 200 words."""

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert DevOps engineer. Provide clear, actionable summaries."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=settings.GROQ_TEMPERATURE,
                max_tokens=400,
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"✗ Error summarizing logs: {e}")
            return f"Error generating summary: {str(e)}"
    
    async def detect_anomaly(
        self,
        current_pattern: str,
        historical_patterns: List[str]
    ) -> Dict[str, Any]:
        """Detect if current pattern is anomalous"""
        if not self.client:
            return {"is_anomaly": False, "confidence": 0.0}
        
        try:
            historical_text = "\n".join(historical_patterns[:10])
            
            prompt = f"""Analyze if the current error pattern is anomalous compared to historical patterns.

Current Pattern:
{current_pattern}

Historical Patterns:
{historical_text}

Respond with JSON:
{{
  "is_anomaly": true/false,
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation",
  "severity": "LOW/MEDIUM/HIGH/CRITICAL"
}}"""

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an anomaly detection expert. Respond only with valid JSON."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.1,
                max_tokens=200,
            )
            
            content = response.choices[0].message.content.strip()
            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]
                content = content.strip()
            
            return json.loads(content)
            
        except Exception as e:
            logger.error(f"✗ Error detecting anomaly: {e}")
            return {"is_anomaly": False, "confidence": 0.0, "error": str(e)}
    
    async def suggest_fix(self, error_analysis: Dict[str, Any]) -> str:
        """Generate fix suggestions for an error"""
        if not self.client:
            return "Groq AI not configured"
        
        try:
            prompt = f"""Given this error analysis, provide actionable fix suggestions:

Error Type: {error_analysis.get('error_type', 'UNKNOWN')}
Severity: {error_analysis.get('severity', 'UNKNOWN')}
Likely Cause: {error_analysis.get('likely_cause', 'Unknown')}
Impact: {error_analysis.get('impact', 'Unknown')}

Provide:
1. Immediate fix (what to do now)
2. Long-term solution (prevent recurrence)
3. Commands or code snippets if applicable
4. Estimated time to fix

Keep response under 150 words."""

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a senior DevOps engineer providing fix suggestions."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=settings.GROQ_TEMPERATURE,
                max_tokens=300,
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"✗ Error generating fix: {e}")
            return f"Error generating fix: {str(e)}"
    
    async def perform_rca(
        self,
        error_logs: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Perform Root Cause Analysis"""
        if not self.client:
            return {"error": "Groq AI not configured"}
        
        try:
            # Prepare error context
            error_summary = "\n".join([
                f"[{log.get('timestamp')}] {log.get('service')}: {log.get('message')[:100]}"
                for log in error_logs[:20]
            ])
            
            prompt = f"""Perform root cause analysis on these errors:

Context:
- Time Period: {context.get('time_period', 'Unknown')}
- Affected Services: {', '.join(context.get('services', []))}
- Total Errors: {context.get('error_count', 0)}

Recent Errors:
{error_summary}

Provide JSON response with:
{{
  "root_cause": "primary root cause",
  "confidence": 0.0-1.0,
  "contributing_factors": ["factor1", "factor2"],
  "evidence": "key evidence supporting this conclusion",
  "recommendation": "immediate action needed"
}}"""

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert in root cause analysis. Respond with valid JSON only."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.2,
                max_tokens=400,
            )
            
            content = response.choices[0].message.content.strip()
            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]
                content = content.strip()
            
            return json.loads(content)
            
        except Exception as e:
            logger.error(f"✗ Error performing RCA: {e}")
            return {"error": str(e)}