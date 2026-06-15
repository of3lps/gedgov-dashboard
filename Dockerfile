# Usa uma imagem oficial do Python, versão enxuta
FROM python:3.11-slim

# Define o diretório de trabalho dentro do container
WORKDIR /app

# Copia o arquivo de dependências primeiro (otimiza o cache do Docker)
COPY requirements.txt .

# Instala as dependências
RUN pip install --no-cache-dir -r requirements.txt

# Copia o restante do código para o container
COPY src/ ./src/

# Comando padrão ao iniciar o container (executará o orquestrador principal)
CMD ["python", "src/main.py"]