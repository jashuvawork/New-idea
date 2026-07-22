# AWS Infrastructure — NexusQuant

## What gets provisioned

`deploy/aws-provision.sh` creates (or reuses) in **ap-south-1**:

| Resource | Spec |
|----------|------|
| EC2 | **m6i.large** (2 vCPU, 8 GiB RAM, dedicated CPU) |
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

## GitHub Actions (auto-deploy on push to `main`)

**Required** repository secrets (Settings → Secrets and variables → Actions):

| Secret | Description |
|--------|-------------|
| `AWS_ACCESS_KEY_ID` | IAM user access key with `ssm:SendCommand` on the EC2 instance |
| `AWS_SECRET_ACCESS_KEY` | Matching secret key |

If either secret is missing, the **Deploy to EC2** workflow fails at *Configure AWS credentials* with:
`Credentials could not be loaded`.

Workflow: `.github/workflows/deploy-ec2.yml`

**Manual deploy** (bypasses GitHub Actions):

```bash
cp deploy/aws.env.example deploy/aws.env   # add same IAM keys
BRANCH=main bash deploy/aws-deploy.sh
```

## Instance sizing

- **m6i.large** (default) — 2 vCPU / 8 GiB, **dedicated CPU**. Replaces t3.large,
  which is *burstable*: under sustained market-hours load (WebSocket + 1s polling +
  scanning) t3 exhausts CPU credits and throttles → intermittent `/health` timeouts.
- **c6i.xlarge** — 4 vCPU / 8 GiB, for heavier load / more scan headroom.
- Region **ap-south-1 (Mumbai)** is optimal — closest to NSE/Upstox. Do not change.
- A bigger instance does **not** beat Upstox API rate limits / caches (vendor-bound).

### Resize an existing running instance (manual — AWS console or CLI)
The running instance type cannot be changed live; stop → modify → start:
```bash
aws ec2 stop-instances --instance-ids <ID> --region ap-south-1
aws ec2 wait instance-stopped --instance-ids <ID> --region ap-south-1
aws ec2 modify-instance-attribute --instance-id <ID> --instance-type m6i.large --region ap-south-1
aws ec2 start-instances --instance-ids <ID> --region ap-south-1
```
Elastic IP + EBS persist across the stop/start, so DNS and data are unaffected.
Verify first: CloudWatch → `CPUCreditBalance` hitting 0 during market hours confirms throttling.

## Costs (approximate)

- m6i.large on-demand ap-south-1: ~$0.10/hr (dedicated 2 vCPU / 8 GiB)
- c6i.xlarge on-demand ap-south-1: ~$0.19/hr (4 vCPU / 8 GiB)
- 50 GB gp3: ~$4/mo
- Elastic IP: free while attached to running instance
