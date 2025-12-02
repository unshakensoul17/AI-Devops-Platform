# scripts/start-local.sh
#!/bin/bash

echo "🚀 Starting AI DevOps Platform (Local)..."

# Check if .env exists
if [ ! -f backend/.env ]; then
    echo "❌ .env file not found!"
    echo "Please create backend/.env with required variables"
    exit 1
fi

# Start services with docker-compose
docker-compose up -d

echo "⏳ Waiting for services to be ready..."
sleep 10

# Check health
echo "🏥 Checking service health..."
curl -s http://localhost:8000/health | jq

echo "✅ Platform is running!"
echo ""
echo "📊 Access points:"
echo "  - API: http://localhost:8000"
echo "  - OpenSearch: http://localhost:9200"
echo "  - Redis: localhost:6379"
echo ""
echo "📝 To view logs:"
echo "  docker-compose logs -f"