FROM python:3.13-slim

WORKDIR /app
COPY llm_security_platform/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY . /app
EXPOSE 8020
CMD ["python", "-m", "uvicorn", "llm_security_platform.app.api:app", "--host", "0.0.0.0", "--port", "8020"]
