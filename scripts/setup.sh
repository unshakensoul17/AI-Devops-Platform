# scripts/setup.sh
#!/bin/bash

echo "🔧 Setting up AI DevOps Platform..."

# Create .env file
cat > backend/.env << EOF
# Auto-generated configuration
ENVIRONMENT=development
DEBUG=true
SECRET_KEY=$(openssl rand -hex 32)

# Redis
REDIS_HOST=redis
REDIS_PORT=6379

# OpenSearch
OPENSEARCH_HOST=opensearch
OPENSEARCH_PORT=9200

# PostgreSQL
POSTGRES_USER=devops
POSTGRES_PASSWORD=devops123
POSTGRES_DB=devops_metadata
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

# Groq AI - ADD YOUR KEY HERE!
GROQ_API_KEY=your-groq-api-key-here

# Processing
BATCH_SIZE=50
ERROR_THRESHOLD=100
EOF

echo "✅ Environment file created at backend/.env"
echo "⚠️  Don't forget to add your GROQ_API_KEY!"
echo ""
echo "🚀 Next steps:"
echo "  1. Add your Groq API key to backend/.env"
echo "  2. Run: docker-compose up -d"
echo "  3. Test: ./scripts/test-ingestion.sh"