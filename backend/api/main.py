# backend/api/main.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import logging
from typing import List, Optional
from datetime import datetime, timedelta
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from database.connection import get_db, init_db
from database.models import LogEntry
from services.queue_service import log_queue
from services.groq_service import GroqAIService
from services.log_processor import LogProcessor
from services.telegram_service import send_telegram_alert
from services.alert_engine import detect_alerts


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

settings = get_settings()

# Global services
groq_service: Optional[GroqAIService] = None
log_processor: Optional[LogProcessor] = None
active_websockets: List[WebSocket] = []
background_task: Optional[asyncio.Task] = None

# ============================================
# BACKGROUND PROCESSING TASK
# ============================================

async def process_queue_continuously():
    """
    Background task that processes logs from the queue.
    Runs inside the web process - NO separate worker needed!
    """
    logger.info("🚀 Starting in-process queue consumer...")
    
    from database.connection import async_session_maker
    from datetime import datetime
    
    while True:
        try:
            # Get batch of logs from queue
            batch = await log_queue.dequeue_batch(
                batch_size=settings.BATCH_SIZE,
                timeout=settings.PROCESSING_INTERVAL
            )
            
            if not batch:
                await asyncio.sleep(1)
                continue
            
            logger.info(f"📦 Processing batch of {len(batch)} logs")
            
            # Process each log
            processed_logs = []
            for raw_log in batch:
                try:
                    processed = await log_processor.process(raw_log)
                    processed_logs.append(processed)
                except Exception as e:
                    logger.error(f"❌ Error processing log: {e}")
                    log_queue.stats['processing_errors'] += 1
            
            # Bulk insert to database
            if processed_logs:
                async with async_session_maker() as session:
                    try:
                        log_entries = []

                        for log in processed_logs:

                            # --- FIX 1: Timestamp conversion ---
                            ts = log.get("timestamp")
                            if isinstance(ts, str):
                                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            ts = ts.replace(tzinfo=None)

                            # --- FIX 2: metadata_ instead of metadata ---
                            entry = LogEntry(
                                id=log.get("id"),
                                timestamp=ts,
                                level=log.get("level"),
                                message=log.get("message"),
                                service=log.get("service"),
                                source=log.get("source"),
                                environment=log.get("environment"),
                                host=log.get("host"),
                                error_type=log.get("error_type"),
                                stack_trace=log.get("stack_trace"),
                                metadata_=log.get("metadata"),
                                ai_analysis=log.get("ai_analysis")
                            )

                            log_entries.append(entry)

                        session.add_all(log_entries)
                        await session.commit()
                        
                        log_queue.stats['total_processed'] += len(processed_logs)
                        logger.info(f"✅ Saved {len(processed_logs)} logs to database")
                        
                        # Broadcast to WebSockets
                        for log in processed_logs:
                            await broadcast_to_websockets(log)
                        alerts = detect_alerts(processed_logs)
                        logger.info(f"🚨 ALERT ENGINE OUTPUT: {alerts}")
                        for alert in alerts:
                            await send_telegram_alert(
                                f"🚨 *AI Log Alert*\n\n{alert}"
                            )

                        
                    except Exception as e:
                        logger.error(f"❌ Database error: {e}")
                        await session.rollback()
            
            # Small delay to prevent tight loop
            await asyncio.sleep(0.1)
            
        except Exception as e:
            logger.error(f"❌ Error in processing loop: {e}")
            await asyncio.sleep(5)


# ============================================
# LIFESPAN EVENTS
# ============================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    global groq_service, log_processor, background_task
    
    logger.info("🚀 Starting AI DevOps Platform (FREE Edition)...")
    
    try:
        # Initialize database
        await init_db()
        
        # Initialize services
        groq_service = GroqAIService()
        log_processor = LogProcessor(groq_service=groq_service)
        
        # Start background processing task (IN-PROCESS!)
        background_task = asyncio.create_task(process_queue_continuously())
        
        logger.info("✅ All services initialized")
        
    except Exception as e:
        logger.error(f"❌ Startup failed: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("🔌 Shutting down...")
    
    if background_task:
        background_task.cancel()
        try:
            await background_task
        except asyncio.CancelledError:
            pass

# Create app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    lifespan=lifespan
)

# CORS
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
    return {
        "service": settings.APP_NAME,
        "version": settings.VERSION,
        "status": "running",
        "plan": "FREE",
        "queue_stats": log_queue.get_stats()
    }

@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Health check"""
    health = {"status": "healthy", "services": {}}
    
    # Check database
    try:
        await db.execute(select(func.count()).select_from(LogEntry))
        health["services"]["database"] = "connected"
    except Exception as e:
        health["services"]["database"] = f"error: {str(e)}"
        health["status"] = "degraded"
    
    # Check queue
    queue_stats = log_queue.get_stats()
    health["services"]["queue"] = {
        "size": queue_stats['current_size'],
        "processed": queue_stats['total_processed']
    }
    
    # Check Groq
    health["services"]["groq_ai"] = "configured" if groq_service.client else "not_configured"
    
    return health

# ============================================
# LOG INGESTION
# ============================================

@app.post("/api/logs/ingest")
async def ingest_log(log_data: dict):
    """Ingest a single log - goes to in-memory queue"""
    try:
        success = await log_queue.enqueue(log_data)
        
        if not success:
            raise HTTPException(status_code=507, detail="Queue is full")
        
        return {
            "success": True,
            "queued": True,
            "queue_size": log_queue.queue.qsize()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error ingesting log: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/logs/ingest/batch")
async def ingest_batch(logs: List[dict]):
    """Ingest multiple logs"""
    try:
        success_count = 0
        for log in logs:
            if await log_queue.enqueue(log):
                success_count += 1
        
        return {
            "success": True,
            "total": len(logs),
            "queued": success_count,
            "failed": len(logs) - success_count
        }
        
    except Exception as e:
        logger.error(f"❌ Error ingesting batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# LOG QUERY
# ============================================

@app.get("/api/logs/search")
async def search_logs(
    query: Optional[str] = None,
    level: Optional[str] = None,
    service: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = Query(100, le=1000),
    db: AsyncSession = Depends(get_db)
):
    """Search logs in PostgreSQL"""
    try:
        # Build query
        stmt = select(LogEntry)
        
        filters = []
        
        if query:
            # PostgreSQL full-text search
            filters.append(LogEntry.message.ilike(f"%{query}%"))
        
        if level:
            filters.append(LogEntry.level == level)
        
        if service:
            filters.append(LogEntry.service == service)
        
        if start_time:
            filters.append(LogEntry.timestamp >= datetime.fromisoformat(start_time))
        
        if end_time:
            filters.append(LogEntry.timestamp <= datetime.fromisoformat(end_time))
        
        if filters:
            stmt = stmt.where(and_(*filters))
        
        stmt = stmt.order_by(LogEntry.timestamp.desc()).limit(limit)
        
        # Execute
        result = await db.execute(stmt)
        logs = result.scalars().all()
        
        # Convert to dict
        return {
            "total": len(logs),
            "logs": [
                {
                    "id": log.id,
                    "timestamp": log.timestamp.isoformat(),
                    "level": log.level,
                    "message": log.message,
                    "service": log.service,
                    "source": log.source,
                    "environment": log.environment,
                    "host": log.host,
                    "error_type": log.error_type,
                    "stack_trace": log.stack_trace,
                    "metadata": log.metadata,
                    "ai_analysis": log.ai_analysis
                }
                for log in logs
            ]
        }
        
    except Exception as e:
        logger.error(f"❌ Search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/logs/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Get log statistics"""
    try:
        # Count by level
        level_stmt = select(
            LogEntry.level,
            func.count(LogEntry.id).label('count')
        ).group_by(LogEntry.level)
        
        level_result = await db.execute(level_stmt)
        by_level = {row.level: row.count for row in level_result}
        
        # Count by service
        service_stmt = select(
            LogEntry.service,
            func.count(LogEntry.id).label('count')
        ).group_by(LogEntry.service).limit(10)
        
        service_result = await db.execute(service_stmt)
        by_service = {row.service: row.count for row in service_result}
        
        # Total count
        total_stmt = select(func.count()).select_from(LogEntry)
        total_result = await db.execute(total_stmt)
        total = total_result.scalar()
        
        return {
            "total_logs": total,
            "by_level": by_level,
            "by_service": by_service,
            "queue_stats": log_queue.get_stats()
        }
        
    except Exception as e:
        logger.error(f"❌ Stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# AI ANALYSIS
# ============================================

@app.post("/api/ai/summarize")
async def summarize_logs(
    start_time: str,
    end_time: str,
    level: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Generate AI summary"""
    try:
        if not groq_service.client:
            raise HTTPException(status_code=503, detail="Groq AI not configured")
        start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00")).replace(tzinfo=None)
        end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00")).replace(tzinfo=None)
        # Fetch logs
        stmt = select(LogEntry).where(
            and_(
                LogEntry.timestamp >= start_dt,
                LogEntry.timestamp <= end_dt
            )
        )
        
        if level:
            stmt = stmt.where(LogEntry.level == level)
        
        stmt = stmt.order_by(LogEntry.timestamp.desc()).limit(50)
        
        result = await db.execute(stmt)
        logs = result.scalars().all()
        
        if not logs:
            return {"summary": "No logs found"}
        
        # Convert to dict for Groq
        log_dicts = [
            {
                "level": log.level,
                "service": log.service,
                "message": log.message,
                "timestamp": log.timestamp.isoformat()
            }
            for log in logs
        ]
        
        summary = await groq_service.summarize_logs(log_dicts)
        
        return {
            "period": {"start": start_time, "end": end_time},
            "total_logs": len(logs),
            "summary": summary
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Summarization error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# WEBSOCKET
# ============================================

@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """Real-time log streaming"""
    await websocket.accept()
    active_websockets.append(websocket)
    logger.info(f"📡 WebSocket connected. Total: {len(active_websockets)}")
    
    try:
        # Send recent logs on connect
        recent = log_queue.get_recent_logs(10)
        for log in recent:
            await websocket.send_json(log)
        
        while True:
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
    """Broadcast to all WebSocket clients"""
    if not active_websockets:
        return
    
    disconnected = []
    for ws in active_websockets:
        try:
            await ws.send_json(log_data)
        except:
            disconnected.append(ws)
    
    for ws in disconnected:
        if ws in active_websockets:
            active_websockets.remove(ws)

# ============================================
# ADMIN ENDPOINTS
# ============================================

@app.delete("/api/admin/cleanup")
async def cleanup_old_logs(
    days: int = Query(7, ge=1, le=30),
    db: AsyncSession = Depends(get_db)
):
    """Delete logs older than X days (FREE tier storage management)"""
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        stmt = select(func.count()).select_from(LogEntry).where(
            LogEntry.timestamp < cutoff_date
        )
        result = await db.execute(stmt)
        count = result.scalar()
        
        # Delete old logs
        delete_stmt = LogEntry.__table__.delete().where(
            LogEntry.timestamp < cutoff_date
        )
        await db.execute(delete_stmt)
        await db.commit()
        
        return {
            "deleted": count,
            "cutoff_date": cutoff_date.isoformat()
        }
    except Exception as e:
            logger.error(f"❌ Cleanup error: {e}")
            raise HTTPException(status_code=500, detail=str(e))           
