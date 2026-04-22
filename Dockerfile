FROM python:3.11-slim

WORKDIR /app

COPY requirements_railway.txt .
RUN pip install --no-cache-dir -r requirements_railway.txt

COPY . .

EXPOSE 5000

CMD ["python", "railway_main.py"]
