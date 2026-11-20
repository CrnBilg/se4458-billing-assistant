FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY indexer.py server.py build_index.py ./
COPY docs ./docs
# Build the index at image build time: the container starts with the index already in place.
RUN python build_index.py
ENV MCP_HOST=0.0.0.0 MCP_PORT=8000
EXPOSE 8000
CMD ["python", "server.py", "--transport", "streamable-http"]
