FROM public.ecr.aws/lambda/python:3.11

# Copy requirements
COPY requirements.txt .

# Install dependencies
RUN pip install -r requirements.txt

# Copy app
COPY app/ ${LAMBDA_TASK_ROOT}/app/

# Set handler
CMD ["app.main.handler"]