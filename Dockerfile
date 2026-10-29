# Starts the MCP server over stdio, for registries that check that it answers introspection
# requests (Glama). Slicing needs Bambu Studio, so real use is on Windows: see the README.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bambu_mcp ./bambu_mcp
COPY run_server.py config.example.json ./
ENV APPDATA=/root/.config
CMD ["python", "run_server.py"]
