# Antes do build, rode `python scripts/preparar_conhecimento.py` (o CI faz isso) para preencher conhecimento/.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY busca_semantica/ busca_semantica/
COPY fontes.json .
COPY conhecimento/ conhecimento/
EXPOSE 8000
CMD ["uvicorn", "busca_semantica.main:app", "--host", "0.0.0.0", "--port", "8000"]
