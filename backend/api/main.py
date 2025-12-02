# backend/api/main.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import logging
from typing import List, Optional
import os

from config.settings import get_settings
from services.redis_stream_service import RedisStreamService
from services.groq_service import GroqAIService
from services.log_processor import LogProcessor
from services.opensearch_client import OpenSearchClient
from services.cache_service import CacheService

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

settings = get_settings()

# Global services
stream_service: Optional[RedisStreamService] = None
groq_service: Optional[GroqAIService] = None
log_processor: Optional[LogProcessor] = None
opensearch: Optional[OpenSearchClient] = None
cache: Optional[CacheService] = None
active_websockets: List[WebSocket] = []

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    global stream_service, groq_service, log_processor, opensearch, cache
    
    logger.info("🚀 Starting AI DevOps Platform API...")
    
    try:
        # Initialize Redis Streams
        stream_service = RedisStreamService(
            redis_url=settings.REDIS_URL,
            stream_name=settings.STREAM_NAME
        )
        await stream_service.connect()
        
        # Initialize Groq AI
        groq_service = GroqAIService()
        
        # Initialize Log Processor
        log_processor = LogProcessor(groq_service=groq_service)
        
        # Initialize OpenSearch
        opensearch = OpenSearchClient(
            hosts=[{
                'host': settings.OPENSEARCH_HOST,
                'port': settings.OPENSEARCH_PORT
            }],
            http_auth=(settings.OPENSEARCH_USERNAME, settings.OPENSEARCH_PASSWORD) if settings.OPENSEARCH_USERNAME else None,
            use_ssl=settings.OPENSEARCH_USE_SSL
        )
        await opensearch.connect()
        
        # Initialize Cache
        cache = CacheService(redis_url=settings.REDIS_URL)
        await cache.connect()
        
        logger.info("✅ All services initialized successfully")
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize services: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("🔌 Shutting down API...")
    
    if stream_service:
        await stream_service.close()
    if opensearch:
        await opensearch.close()
    if cache:
        await cache.close()

# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================
# ENDPOINTS
# ============================================

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": settings.APP_NAME,
        "version": settings.VERSION,
        "status": "running",
        "environment": settings.ENVIRONMENT
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    health = {
        "status": "healthy",
        "services": {}
    }
    
    # Check Redis
    try:
        if stream_service:
            await stream_service.client.ping()
            health["services"]["redis"] = "connected"
    except Exception as e:
        health["services"]["redis"] = f"error: {str(e)}"
        health["status"] = "degraded"
    
    # Check OpenSearch
    try:
        if opensearch:
            await opensearch.client.info()
            health["services"]["opensearch"] = "connected"
    except Exception as e:
        health["services"]["opensearch"] = f"error: {str(e)}"
        health["status"] = "degraded"
    
    # Check Groq
    health["services"]["groq_ai"] = "configured" if groq_service.client else "not_configured"
    
    return health

# ============================================
# LOG INGESTION
# ============================================

@app.post("/api/logs/ingest")
async def ingest_log(log_data: dict):
    """Ingest a single log entry"""
    try:
        # Add to Redis Stream
        message_id = await stream_service.produce(log_data)
        
        # Also process immediately for WebSocket (optional)
        if active_websockets:
            processed = await log_processor.process(log_data)
            await broadcast_to_websockets(processed)
        
        return {
            "success": True,
            "message_id": message_id
        }
        
    except Exception as e:
        logger.error(f"❌ Error ingesting log: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/logs/ingest/batch")
async def ingest_logs_batch(logs: List[dict]):
    """Ingest multiple logs"""
    try:
        count = await stream_service.produce_batch(logs)
        
        return {
            "success": True,
            "count": count
        }
        
    except Exception as e:
        logger.error(f"❌ Error ingesting batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# LOG SEARCH & QUERY
# ============================================

@app.get("/api/logs/search")
async def search_logs(
    query: Optional[str] = None,
    level: Optional[str] = None,
    service: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    size: int = 100
):
    """Search logs"""
    try:
        # Check cache
        cache_key = f"search:{query}:{level}:{service}:{start_time}:{end_time}:{size}"
        cached = await cache.get(cache_key)
        
        if cached:
            return cached
        
        # Query OpenSearch
        results = await opensearch.search_logs(
            query=query,
            level=level,
            service=service,
            start_time=start_time,
            end_time=end_time,
            size=size
        )
        
        # Cache for 60 seconds
        await cache.set(cache_key, results, expire=60)
        
        return results
        
    except Exception as e:
        logger.error(f"❌ Error searching logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/logs/stats")
async def get_stats():
    """Get log statistics"""
    try:
        # Get from Redis cache
        stats = {
            "by_level": {},
            "by_service": {},
            "by_error_type": {}
        }
        
        if cache.client:
            # Get level counts
            level_counts = await cache.client.hgetall('stats:logs:level')
            stats["by_level"] = {k: int(v) for k, v in level_counts.items()}
            
            # Get service counts
            service_counts = await cache.client.hgetall('stats:logs:service')
            stats["by_service"] = {k: int(v) for k, v in service_counts.items()}
            
            # Get error type counts
            error_counts = await cache.client.hgetall('stats:errors:type')
            stats["by_error_type"] = {k: int(v) for k, v in error_counts.items()}
        
        return stats
        
    except Exception as e:
        logger.error(f"❌ Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# AI ANALYSIS
# ============================================

@app.post("/api/ai/analyze")
async def analyze_log_with_ai(log_data: dict):
    """Analyze a log with Groq AI"""
    try:
        if not groq_service.client:
            raise HTTPException(status_code=503, detail="Groq AI not configured")
        
        analysis = await groq_service.analyze_log(log_data)
        
        return {
            "log": log_data,
            "analysis": analysis
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error analyzing log: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ai/summarize")
async def summarize_logs_with_ai(
    start_time: str,
    end_time: str,
    level: Optional[str] = None,
    service: Optional[str] = None
):
    """Generate AI summary of logs"""
    try:
        if not groq_service.client:
            raise HTTPException(status_code=503, detail="Groq AI not configured")
        
        # Fetch logs
        results = await opensearch.search_logs(
            level=level,
            service=service,
            start_time=start_time,
            end_time=end_time,
            size=100
        )
        
        logs = results.get('logs', [])
        
        if not logs:
            return {"summary": "No logs found for the specified period"}
        
        # Generate summary
        summary = await groq_service.summarize_logs(logs)
        
        return {
            "period": {"start": start_time, "end": end_time},
            "total_logs": len(logs),
            "summary": summary
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error summarizing: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ai/rca")
async def perform_root_cause_analysis(
    start_time: str,
    end_time: str,
    services: Optional[List[str]] = None
):
    """Perform root cause analysis"""
    try:
        if not groq_service.client:
            raise HTTPException(status_code=503, detail="Groq AI not configured")
        
        # Fetch error logs
        error_logs = []
        for level in ['ERROR', 'CRITICAL', 'FATAL']:
            results = await opensearch.search_logs(
                level=level,
                start_time=start_time,
                end_time=end_time,
                size=500
            )
            error_logs.extend(results.get('logs', []))
        
        if not error_logs:
            return {"analysis": "No errors found in the specified period"}
        
        # Prepare context
        context = {
            "time_period": f"{start_time} to {end_time}",
            "services": list(set(log['service'] for log in error_logs)),
            "error_count": len(error_logs)
        }
        
        # Perform RCA
        rca = await groq_service.perform_rca(error_logs[:50], context)
        
        return {
            "period": {"start": start_time, "end": end_time},
            "total_errors": len(error_logs),
            "affected_services": context['services'],
            "root_cause_analysis": rca
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error performing RCA: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# STREAM MANAGEMENT
# ============================================

@app.get("/api/stream/info")
async def get_stream_info():
    """Get Redis Stream info"""
    try:
        info = await stream_service.get_stream_info()
        return info
    except Exception as e:
        logger.error(f"❌ Error getting stream info: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# WEBSOCKET
# ============================================

@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """WebSocket endpoint for real-time logs"""
    await websocket.accept()
    active_websockets.append(websocket)
    logger.info(f"📡 WebSocket connected. Total: {len(active_websockets)}")
    
    try:
        while True:
            # Keep connection alive
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
                
    except WebSocketDisconnect:
        active_websockets.remove(websocket)
        logger.info(f"📴 WebSocket disconnected. Total: {len(active_websockets)}")
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}")
        if websocket in active_websockets:
            active_websockets.remove(websocket)

async def broadcast_to_websockets(log_data: dict):
    """Broadcast log to all connected WebSockets"""
    if not active_websockets:
        return
    
    disconnected = []
    for ws in active_websockets:
        try:
            await ws.send_json(log_data)
        except Exception as e:
            logger.error(f"❌ Error broadcasting: {e}")
            disconnected.append(ws)
    
    # Remove disconnected
    for ws in disconnected:
        if ws in active_websockets:
            active_websockets.remove(ws)

# ============================================
# RUN
# ============================================

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.environ.get("PORT", 8000))
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=settings.DEBUG,
        log_level="info"
    )