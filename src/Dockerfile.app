FROM python:3.11-slim

WORKDIR /workspace

# Install core packages from requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy production source code (which is populated after REVIEWER_REFACTOR promotion)
COPY . /workspace/src

ENV PYTHONPATH=/workspace

EXPOSE 8000

CMD ["uvicorn", "src.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
