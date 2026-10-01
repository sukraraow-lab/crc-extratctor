FROM python:3.12-slim

# Render par ffmpeg install karne ke liye
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Requirements install karna
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Baaki saara code copy karna
COPY . .

# Bot start karne ki command
CMD ["python", "main.py"]
