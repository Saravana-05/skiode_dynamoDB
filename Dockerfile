# ── AWS Lambda container image for FastAPI (Python 3.12) ──────────────────────
# Base image: AWS-managed Lambda runtime — includes the Lambda RIC and correct
# directory layout. LAMBDA_TASK_ROOT is pre-set to /var/task.
FROM public.ecr.aws/lambda/python:3.12

# Install Python dependencies into the Lambda task root so they are on sys.path
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# Copy application source — puts app/ at /var/task/app/
COPY app/ ${LAMBDA_TASK_ROOT}/app/

# DO NOT copy .env — all config is supplied via Lambda Environment Variables.
# Set these in the Lambda console (or via terraform / SAM):
#   DB_BACKEND            dynamodb  |  postgresql
#   DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, DB_SSLMODE
#   AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY  (or use IAM role)
#   GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI
#   OUTLOOK_CLIENT_ID, OUTLOOK_CLIENT_SECRET, OUTLOOK_REDIRECT_URI
#   DJANGO_SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
#   REFRESH_TOKEN_EXPIRE_DAYS, EMAIL_HOST, EMAIL_PORT
#   EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, SITE_URL

# Lambda handler — matches handler = Mangum(app) in app/main.py
CMD ["app.main.handler"]
