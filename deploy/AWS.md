# AWS Infrastructure — NexusQuant

## What gets provisioned

`deploy/aws-provision.sh` creates (or reuses) in **ap-south-1**:

| Resource | Spec |
|----------|------|
| EC2 | **t3.large** (2 vCPU, 8 GiB RAM) |
| Root volume | **50 GB gp3** encrypted |
| OS | Amazon Linux 2023 |
| IAM | `NexusQuantSSMProfile` (SSM deploy, no SSH required) |
| Security group | TCP 22, 80, 443, 8000 |
| Elastic IP | Stable public IP for DNS + Vercel rewrites |
| SSH key | `deploy/nexusquant-ec2.pem` (gitignored) |

User-data (`deploy/ec2-userdata.sh`) installs Docker, clones the repo, builds `docker-compose.prod.yml` (backend + Redis).

## One-time setup

```bash
cp deploy/aws.env.example deploy/aws.env
# Add AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY (IAM user with EC2 + SSM)

./deploy/aws-provision.sh
```

State is written to `deploy/aws-infra.state` (gitignored).

## DNS (required)

| Record | Type | Value |
|--------|------|-------|
| `api.jashuvatrade.xyz` | A | Elastic IP from provision output |

**Vercel** (`vercel.json`) proxies `www.jashuvatrade.xyz/api/*` to `http://<EIP>:8000`. Update the IP in `vercel.json` when the Elastic IP changes, then redeploy frontend.

## HTTPS on EC2

After `api.jashuvatrade.xyz` DNS points to the Elastic IP:

```bash
ssh -i deploy/nexusquant-ec2.pem ec2-user@<EIP> \
  'sudo bash /opt/nexusquant/New-idea/deploy/setup-https.sh'
```

## Deploy backend

```bash
# Via SSM (recommended)
BRANCH=main ./deploy/aws-deploy.sh

# Via SSH
EC2_HOST=<EIP> EC2_KEY=deploy/nexusquant-ec2.pem ./deploy/ec2-deploy-one-liner.sh
```

## Verify

```bash
curl http://<EIP>:8000/health
curl https://www.jashuvatrade.xyz/api/deployment/status
```

## Secrets on the instance

Production env lives at `/opt/nexusquant/env` (not in git). Add after first boot:

- `UPSTOX_API_KEY`, `UPSTOX_API_SECRET`
- `FINNHUB_API_KEY`
- `CURSOR_API_KEY` (optional, for Composer monitor)

## GitHub Actions

Set repository secrets:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

Workflow `.github/workflows/deploy-ec2.yml` deploys on push to `main`.

## Costs (approximate)

- t3.large on-demand ap-south-1: ~$0.08/hr
- 50 GB gp3: ~$4/mo
- Elastic IP: free while attached to running instance
