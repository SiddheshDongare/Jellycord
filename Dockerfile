# Use an official Python runtime as a parent image
FROM python:3.12.10-slim

# Set the working directory in the container
WORKDIR /app

# Prevent Python from writing pyc files to disc (optional)
ENV PYTHONDONTWRITEBYTECODE=1
# Ensure Python output is sent straight to terminal (useful for logging)
ENV PYTHONUNBUFFERED=1

# Install system dependencies (if any) - none specific needed for this app
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     package1 package2 && \
#     apt-get clean && \
#     rm -rf /var/lib/apt/lists/*

# Install Python dependencies
# Copy only the requirements file first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Command to run the application
CMD ["python", "main.py"]
