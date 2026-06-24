#!/bin/bash
# NexusQuant AWS EC2 deployment script
set -euo pipefail

REGION="${AWS_REGION:-ap-south-1}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.small}"
KEY_NAME="${KEY_NAME:-nexusquant-key}"
SG_NAME="nexusquant-sg"
INSTANCE_NAME="nexusquant-backend"
AMI_ID=$(aws ec2 describe-images \
  --owners amazon \
  --filters "Name=name,Values=al2023-ami-2023*-x86_64" "Name=state,Values=available" \
  --query 'sort_by(Images, &CreationDate)[-1].ImageId' \
  --output text --region "$REGION")

echo "==> Using AMI: $AMI_ID in $REGION"

# Security group
SG_ID=$(aws ec2 describe-security-groups --group-names "$SG_NAME" --region "$REGION" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "None")

if [ "$SG_ID" = "None" ] || [ -z "$SG_ID" ]; then
  SG_ID=$(aws ec2 create-security-group \
    --group-name "$SG_NAME" \
    --description "NexusQuant backend" \
    --region "$REGION" \
    --query 'GroupId' --output text)
  aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --region "$REGION" \
    --protocol tcp --port 22 --cidr 0.0.0.0/0
  aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --region "$REGION" \
    --protocol tcp --port 80 --cidr 0.0.0.0/0
  aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --region "$REGION" \
    --protocol tcp --port 443 --cidr 0.0.0.0/0
  aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --region "$REGION" \
    --protocol tcp --port 8000 --cidr 0.0.0.0/0
  echo "==> Created security group: $SG_ID"
fi

# User data — install Docker and run NexusQuant
USER_DATA=$(cat <<'UDATA'
#!/bin/bash
yum update -y
yum install -y docker git
systemctl start docker
systemctl enable docker
usermod -aG docker ec2-user

mkdir -p /opt/nexusquant
cd /opt/nexusquant

# Clone repo (will be overwritten by deploy step)
cat > /opt/nexusquant/docker-compose.yml << 'COMPOSE'
services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped
  backend:
    image: nexusquant-backend:latest
    ports:
      - "8000:8000"
    env_file:
      - /opt/nexusquant/env
    environment:
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
    restart: unless-stopped
COMPOSE

touch /opt/nexusquant/env
echo "Deployed at $(date)" > /opt/nexusquant/deploy.log
UDATA
)

ENCODED_USER_DATA=$(echo "$USER_DATA" | base64 -w 0)

# Launch instance
INSTANCE_ID=$(aws ec2 run-instances \
  --image-id "$AMI_ID" \
  --instance-type "$INSTANCE_TYPE" \
  --key-name "$KEY_NAME" \
  --security-group-ids "$SG_ID" \
  --user-data "$USER_DATA" \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$INSTANCE_NAME}]" \
  --region "$REGION" \
  --query 'Instances[0].InstanceId' \
  --output text 2>/dev/null || \
  aws ec2 run-instances \
  --image-id "$AMI_ID" \
  --instance-type "$INSTANCE_TYPE" \
  --security-group-ids "$SG_ID" \
  --user-data "$USER_DATA" \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$INSTANCE_NAME}]" \
  --region "$REGION" \
  --query 'Instances[0].InstanceId' \
  --output text)

echo "==> Launched instance: $INSTANCE_ID"
echo "==> Waiting for running state..."
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --region "$REGION"

PUBLIC_IP=$(aws ec2 describe-instances \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' \
  --output text)

echo "==> Instance running at: $PUBLIC_IP"
echo "==> API will be at: http://$PUBLIC_IP:8000"
echo "$PUBLIC_IP" > /tmp/nexusquant-ec2-ip.txt
