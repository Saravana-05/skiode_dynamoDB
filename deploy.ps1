# ── Lambda Docker Image — Build & Push to ECR ────────────────────────────────
# Run from:  G:\skiode_lambda_backend\fastapi_service\fastapi_service\
#
# Before running:
#   1. Install AWS CLI  https://aws.amazon.com/cli/
#   2. Run: aws configure   (enter your Access Key, Secret, region ap-south-1)
#   3. Fill in your values below

# ── CONFIG — edit these ──────────────────────────────────────────────────────
$AWS_REGION     = "ap-south-1"           # your Lambda region
$AWS_ACCOUNT_ID = "065504275239"      # 12-digit AWS account ID
$ECR_REPO_NAME  = "skiode-lambda-container"       # ECR repository name
$IMAGE_TAG      = "latest"
$LAMBDA_FUNC    = "skiode_backend_qa"   # exact Lambda function name
# ─────────────────────────────────────────────────────────────────────────────

$ECR_URI = "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}"

Write-Host "`n[1/5] Logging in to ECR..." -ForegroundColor Cyan
aws ecr get-login-password --region $AWS_REGION |
    docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

Write-Host "`n[2/5] Creating ECR repo (skipped if already exists)..." -ForegroundColor Cyan
aws ecr create-repository --repository-name $ECR_REPO_NAME --region $AWS_REGION 2>$null

Write-Host "`n[3/5] Building Docker image..." -ForegroundColor Cyan
# --provenance=false forces Docker V2 Schema 2 manifest (required by Lambda).
# Without it, BuildKit outputs OCI format which Lambda rejects.
docker build --platform linux/amd64 --provenance=false -t "${ECR_REPO_NAME}:${IMAGE_TAG}" .

Write-Host "`n[4/5] Tagging and pushing to ECR..." -ForegroundColor Cyan
docker tag "${ECR_REPO_NAME}:${IMAGE_TAG}" "${ECR_URI}:${IMAGE_TAG}"
docker push "${ECR_URI}:${IMAGE_TAG}"

Write-Host "`n[5/5] Updating Lambda function with new image..." -ForegroundColor Cyan
aws lambda update-function-code `
    --function-name $LAMBDA_FUNC `
    --image-uri "${ECR_URI}:${IMAGE_TAG}" `
    --region $AWS_REGION

Write-Host "`nDone! Lambda updated with image: ${ECR_URI}:${IMAGE_TAG}" -ForegroundColor Green
