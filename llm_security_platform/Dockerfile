FROM python:3.13-slim

WORKDIR /app
COPY llm_security_platform/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY . /app

# Non-root user execution setup
RUN groupadd -r -g 1000 appgroup && useradd -r -u 1000 -g appgroup appuser \
    && chown -R appuser:appgroup /app
USER appuser

EXPOSE 8020
CMD ["python", "-m", "uvicorn", "llm_security_platform.app.api:app", "--host", "0.0.0.0", "--port", "8020"]
