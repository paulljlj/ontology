FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends default-jre-headless \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-satellite.txt ./
# DuckDB/Filesystem MCP keep their own runtime.  Only the standalone official
# Neo4j MCP binary is installed beside the API because the diagnosis launches
# it over stdio.
RUN pip install --no-cache-dir -r requirements.txt -r requirements-satellite.txt neo4j-mcp-server==1.6.0

COPY app ./app
COPY satellite_diagnosis ./satellite_diagnosis
COPY scripts ./scripts

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
