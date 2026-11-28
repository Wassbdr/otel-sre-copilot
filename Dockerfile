# Offline image: replay demo and benchmark on the bundled snapshots, no cluster needed.
#   docker build -t otel-sre-copilot .
#   docker run --rm -it otel-sre-copilot                       # recorded investigation
#   docker run --rm -it -e NIM_API_KEY otel-sre-copilot --live  # live LLM on a snapshot
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY eval ./eval
RUN pip install --quiet .
COPY scenarios ./scenarios
COPY snapshots ./snapshots
COPY examples ./examples
COPY artifacts ./artifacts
COPY results ./results
ENTRYPOINT ["sre-copilot-demo"]
