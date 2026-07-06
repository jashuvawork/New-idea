#!/usr/bin/env bash
# Provision NexusQuant AWS stack: security group, EC2 t3.large (50GB), Elastic IP, SSM.
#
# Prerequisites:
#   cp deploy/aws.env.example deploy/aws.env
#   # fill AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY
#
# Usage:
#   ./deploy/aws-provision.sh
#
# Optional env overrides:
#   INSTANCE_TYPE=t3.large
#   ROOT_VOLUME_GB=50
#   KEY_NAME=nexusquant-ec2
#   PROJECT_NAME=nexusquant

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/aws.env"
STATE_FILE="${SCRIPT_DIR}/aws-infra.state"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: missing $ENV_FILE"
  exit 1
fi

# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a

: "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID required}"
: "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY required}"

export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-ap-south-1}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.large}"
ROOT_VOLUME_GB="${ROOT_VOLUME_GB:-50}"
KEY_NAME="${KEY_NAME:-nexusquant-ec2}"
PROJECT_NAME="${PROJECT_NAME:-nexusquant}"
IAM_PROFILE="${IAM_INSTANCE_PROFILE:-NexusQuantSSMProfile}"
REPO_BRANCH="${REPO_BRANCH:-main}"

echo "==> NexusQuant AWS provision ($AWS_DEFAULT_REGION)"
echo "    instance=$INSTANCE_TYPE volume=${ROOT_VOLUME_GB}GB profile=$IAM_PROFILE"

VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
SUBNET_ID=$(aws ec2 describe-subnets \
  --filters Name=vpc-id,Values="$VPC_ID" Name=default-for-az,Values=true \
  --query 'Subnets[0].SubnetId' --output text)
AMI_ID=$(aws ec2 describe-images --owners amazon \
  --filters "Name=name,Values=al2023-ami-2023*" "Name=architecture,Values=x86_64" "Name=state,Values=available" \
  --query 'sort_by(Images,&CreationDate)[-1].ImageId' --output text)

echo "VPC=$VPC_ID subnet=$SUBNET_ID ami=$AMI_ID"

# --- security group ---
SG_NAME="${PROJECT_NAME}-ec2-sg"
SG_ID=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=$SG_NAME" "Name=vpc-id,Values=$VPC_ID" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)

if [ -z "$SG_ID" ] || [ "$SG_ID" = "None" ]; then
  echo "==> Creating security group $SG_NAME"
  SG_ID=$(aws ec2 create-security-group \
    --group-name "$SG_NAME" \
    --description "NexusQuant EC2 HTTP HTTPS API SSH" \
    --vpc-id "$VPC_ID" \
    --query GroupId --output text)
  for spec in "22:NexusQuant SSH" "80:HTTP" "443:HTTPS" "8000:FastAPI backend"; do
    port="${spec%%:*}"
    desc="${spec#*:}"
    aws ec2 authorize-security-group-ingress \
      --group-id "$SG_ID" \
      --ip-permissions "IpProtocol=tcp,FromPort=$port,ToPort=$port,IpRanges=[{CidrIp=0.0.0.0/0,Description=\"$desc\"}]" \
      >/dev/null
  done
else
  echo "==> Reusing security group $SG_ID"
fi

# --- SSH key pair (optional emergency access) ---
KEY_FILE="${SCRIPT_DIR}/${KEY_NAME}.pem"
if ! aws ec2 describe-key-pairs --key-names "$KEY_NAME" >/dev/null 2>&1; then
  echo "==> Creating key pair $KEY_NAME -> $KEY_FILE"
  aws ec2 create-key-pair --key-name "$KEY_NAME" --query KeyMaterial --output text > "$KEY_FILE"
  chmod 400 "$KEY_FILE"
else
  echo "==> Key pair $KEY_NAME already exists"
fi

# --- skip launch if instance already tagged ---
EXISTING_ID=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=${PROJECT_NAME}-ec2" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text 2>/dev/null || true)

if [ -n "$EXISTING_ID" ] && [ "$EXISTING_ID" != "None" ]; then
  INSTANCE_ID="$EXISTING_ID"
  echo "==> Reusing existing instance $INSTANCE_ID"
else
  USERDATA_B64=$(base64 -w0 "${SCRIPT_DIR}/ec2-userdata.sh" 2>/dev/null || base64 "${SCRIPT_DIR}/ec2-userdata.sh" | tr -d '\n')

  echo "==> Launching $INSTANCE_TYPE (${ROOT_VOLUME_GB}GB gp3) ..."
  INSTANCE_ID=$(aws ec2 run-instances \
    --image-id "$AMI_ID" \
    --instance-type "$INSTANCE_TYPE" \
    --key-name "$KEY_NAME" \
    --subnet-id "$SUBNET_ID" \
    --security-group-ids "$SG_ID" \
    --iam-instance-profile "Name=$IAM_PROFILE" \
    --associate-public-ip-address \
    --block-device-mappings "[{\"DeviceName\":\"/dev/xvda\",\"Ebs\":{\"VolumeSize\":${ROOT_VOLUME_GB},\"VolumeType\":\"gp3\",\"DeleteOnTermination\":true,\"Encrypted\":true}}]" \
    --user-data "$USERDATA_B64" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${PROJECT_NAME}-ec2},{Key=Project,Value=${PROJECT_NAME}},{Key=Branch,Value=${REPO_BRANCH}}]" \
    --metadata-options "HttpTokens=required,HttpEndpoint=enabled" \
    --monitoring Enabled=true \
    --query 'Instances[0].InstanceId' --output text)

  echo "==> Waiting for instance running: $INSTANCE_ID"
  aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"
fi

# --- Elastic IP ---
EIP_ALLOC=$(aws ec2 describe-addresses \
  --filters "Name=tag:Name,Values=${PROJECT_NAME}-eip" \
  --query 'Addresses[0].AllocationId' --output text 2>/dev/null || true)

if [ -z "$EIP_ALLOC" ] || [ "$EIP_ALLOC" = "None" ]; then
  echo "==> Allocating Elastic IP"
  EIP_ALLOC=$(aws ec2 allocate-address --domain vpc \
    --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=${PROJECT_NAME}-eip},{Key=Project,Value=${PROJECT_NAME}}]" \
    --query AllocationId --output text)
fi

CURRENT_EIP_INSTANCE=$(aws ec2 describe-addresses --allocation-ids "$EIP_ALLOC" \
  --query 'Addresses[0].InstanceId' --output text 2>/dev/null || true)

if [ "$CURRENT_EIP_INSTANCE" != "$INSTANCE_ID" ]; then
  echo "==> Associating Elastic IP to $INSTANCE_ID"
  aws ec2 associate-address --instance-id "$INSTANCE_ID" --allocation-id "$EIP_ALLOC" >/dev/null
fi

PUBLIC_IP=$(aws ec2 describe-addresses --allocation-ids "$EIP_ALLOC" --query 'Addresses[0].PublicIp' --output text)

# --- persist state ---
cat > "$STATE_FILE" <<EOF
# Generated $(date -Iseconds) — do not commit secrets
AWS_DEFAULT_REGION=$AWS_DEFAULT_REGION
EC2_INSTANCE_ID=$INSTANCE_ID
EC2_PUBLIC_IP=$PUBLIC_IP
EC2_SECURITY_GROUP_ID=$SG_ID
EC2_KEY_NAME=$KEY_NAME
EC2_INSTANCE_TYPE=$INSTANCE_TYPE
EC2_ROOT_VOLUME_GB=$ROOT_VOLUME_GB
EIP_ALLOCATION_ID=$EIP_ALLOC
EOF

# --- update aws.env instance id ---
if grep -q '^EC2_INSTANCE_ID=' "$ENV_FILE"; then
  sed -i "s|^EC2_INSTANCE_ID=.*|EC2_INSTANCE_ID=$INSTANCE_ID|" "$ENV_FILE"
else
  echo "EC2_INSTANCE_ID=$INSTANCE_ID" >> "$ENV_FILE"
fi

echo ""
echo "==> Provisioned successfully"
echo "    Instance ID : $INSTANCE_ID"
echo "    Public IP   : $PUBLIC_IP"
echo "    Type        : $INSTANCE_TYPE / ${ROOT_VOLUME_GB}GB gp3"
echo "    Security grp: $SG_ID"
echo "    SSH key     : $KEY_FILE"
echo ""
echo "Next steps:"
echo "  1. Point DNS:"
echo "       api.jashuvatrade.xyz  A  -> $PUBLIC_IP"
echo "       (Vercel www rewrites to this IP:8000 — update vercel.json if IP changed)"
echo "  2. Wait ~3-5 min for userdata bootstrap, then verify:"
echo "       curl http://$PUBLIC_IP:8000/health"
echo "  3. HTTPS on instance:"
echo "       ssh -i $KEY_FILE ec2-user@$PUBLIC_IP 'sudo bash /opt/nexusquant/New-idea/deploy/setup-https.sh'"
echo "  4. Deploy latest code via SSM:"
echo "       BRANCH=main ./deploy/aws-deploy.sh"
echo ""
echo "State saved to $STATE_FILE"

# --- wait for SSM ---
echo "==> Waiting for SSM agent (up to 5 min) ..."
for i in $(seq 1 30); do
  STATUS=$(aws ssm describe-instance-information \
    --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
    --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "")
  if [ "$STATUS" = "Online" ]; then
    echo "SSM Online"
    break
  fi
  echo "  $i: ${STATUS:-Pending}"
  sleep 10
done
