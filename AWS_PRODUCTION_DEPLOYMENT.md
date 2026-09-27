# AWS Production Deployment Runbook - Right Route Backend

This guide deploys the Django backend to AWS `us-east-1` using:

- RDS PostgreSQL for the production database
- S3 for uploaded media files
- ECR as the Docker image registry
- EC2 with an Elastic IP as the runtime server
- GitHub Actions for CI/CD
- Docker Compose under `/opt/rightroute-backend`
- Putty for manual EC2 terminal access from Windows

For now the app runs on `http://ELASTIC_IP`. Later, add a domain and SSL.

---

## 1. Local repo files added for production

The deployment uses these files:

- `.github/workflows/deploy.yml` - builds Docker image, pushes to ECR, SSH deploys to EC2
- `docker-compose.prod.yml` - production backend + Nginx runtime
- `nginx/conf.d/right-route.conf` - HTTP reverse proxy for the Elastic IP
- `production.example.env` - template for the real server-only env file

The real production env file must be created on EC2 only:

```bash
/opt/rightroute-backend/production.env
```

Do not commit `production.env`.

---

## 2. AWS region

Use this region everywhere:

```text
us-east-1
```

---

## 3. Create ECR repository

AWS Console:

1. Go to **ECR**.
2. Choose **Create repository**.
3. Visibility: **Private**.
4. Repository name:

```text
rightroute-backend
```

5. Create the repository.

Keep the repository URI. It will look like:

```text
AWS_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/rightroute-backend
```

---

## 4. Create S3 bucket for media

AWS Console:

1. Go to **S3**.
2. Create bucket.
3. Bucket name example:

```text
rightroute-prod-media
```

4. Region: `us-east-1`.
5. Keep **Block all public access** enabled unless the product needs public direct media URLs.
6. Enable bucket versioning if possible.
7. Create bucket.

Current app config can generate public-style S3 media URLs if `AWS_QUERYSTRING_AUTH=False`. If media should be private, set `AWS_QUERYSTRING_AUTH=True` and use signed URLs later where needed.

Recommended for now:

```env
USE_S3=True
AWS_STORAGE_BUCKET_NAME=rightroute-prod-media
AWS_QUERYSTRING_AUTH=False
```

---

## 5. Create RDS PostgreSQL

AWS Console:

1. Go to **RDS**.
2. Create database.
3. Engine: **PostgreSQL**.
4. Template: Production or Dev/Test depending budget.
5. DB identifier:

```text
rightroute-prod-db
```

6. Master username example:

```text
rightroute_admin
```

7. Set a strong password and save it securely.
8. Region: `us-east-1`.
9. Public access: **No**.
10. VPC: same VPC where EC2 will run.
11. Create or select a DB security group.
12. Initial database name:

```text
rightroute_prod
```

After creation, copy the RDS endpoint. It will look like:

```text
rightroute-prod-db.xxxxxx.us-east-1.rds.amazonaws.com
```

Security group rule for RDS:

- Type: PostgreSQL
- Port: `5432`
- Source: the EC2 security group, not `0.0.0.0/0`

---

## 6. Create IAM role for EC2

Create an IAM role for EC2 so the server can pull from ECR and access S3 without storing AWS keys on the server.

IAM role trust type:

```text
AWS service -> EC2
```

Attach these permissions, preferably as scoped custom policies:

ECR pull permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage"
      ],
      "Resource": "*"
    }
  ]
}
```

S3 media permissions for the bucket:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::rightroute-prod-media",
        "arn:aws:s3:::rightroute-prod-media/*"
      ]
    }
  ]
}
```

Attach this role to the EC2 instance.

---

## 7. Create EC2 instance

AWS Console:

1. Go to **EC2 -> Instances**.
2. Choose **Launch instance**.
3. Name the server:

```text
rightroute-backend-prod
```

Recommended starter instance:

```text
Instance family: t3.small or t3.medium
Operating system: Ubuntu Server 24.04 LTS
Architecture: 64-bit x86
```

Use `t3.small` for a light initial production launch. Use `t3.medium` if you expect heavier API traffic, larger route-processing jobs, or more background/server load. The app will run Docker, Nginx, and Gunicorn on this server, so avoid `t2.micro`/`t3.micro` for production unless it is only a temporary smoke test.

AMI / operating system:

1. In **Application and OS Images**, choose **Ubuntu**.
2. Select **Ubuntu Server 24.04 LTS**.
3. Select the normal **64-bit x86** AMI unless you intentionally choose an ARM instance type.
4. Keep note of the default username for this AMI:

```text
ubuntu
```

This username is needed later for Putty and GitHub Actions:

```text
EC2_USER=ubuntu
```

Instance type:

1. Choose `t3.small` for the first production deployment.
2. Choose `t3.medium` if budget allows and you want more comfortable memory/CPU headroom.
3. Do not choose `micro` for a real production deployment because Docker, Nginx, Gunicorn, migrations, and route-related processing can use more memory than a micro instance comfortably provides.

Key pair for SSH / Putty:

1. In **Key pair (login)**, choose **Create new key pair** unless you already have a production key pair.
2. Key pair name:

```text
rightroute-prod-key
```

3. Key pair type: **RSA**.
4. Private key file format:

```text
.pem
```

5. Download the `.pem` file and store it safely. AWS will not let you download it again.
6. For Putty, convert the `.pem` file to `.ppk` using **Puttygen**:
   - Open Puttygen.
   - Click **Load**.
   - Select the downloaded `.pem` file.
   - Click **Save private key**.
   - Save it as something like `rightroute-prod-key.ppk`.
7. Keep both files private. Do not commit them to GitHub and do not paste them into chat.

Network settings:

1. VPC: select the same VPC used by the RDS database from step 5.
2. Subnet: choose a **public subnet** in that VPC.
3. Auto-assign public IP: enable it for first access if needed. The permanent IP will be attached in step 8 using Elastic IP.
4. IAM instance profile: attach the EC2 IAM role created in step 6. This role should allow:
   - Pulling Docker images from ECR.
   - Reading/writing media files in the S3 bucket.
5. If the IAM role does not show in the EC2 launch screen, finish creating the instance first, then attach it from:

```text
EC2 -> Instances -> select instance -> Actions -> Security -> Modify IAM role
```

Create/select EC2 security group:

Use a dedicated security group for this backend server. Recommended name:

```text
rightroute-backend-prod-sg
```

Inbound rules:

| Type | Protocol | Port | Source | Notes |
| --- | --- | --- | --- | --- |
| SSH | TCP | 22 | Your current IP only | Required for Putty access. Do not use `0.0.0.0/0` for SSH. |
| HTTP | TCP | 80 | `0.0.0.0/0` | Required now for Elastic IP access through Nginx. |
| HTTPS | TCP | 443 | `0.0.0.0/0` | Add now or later. Required when domain + SSL are added. |

For SSH source, choose **My IP** in the AWS console. It should create a rule like:

```text
YOUR_PUBLIC_IP/32
```

If your internet IP changes later, update the SSH rule to your new IP. Do not open SSH to everyone unless it is a very temporary emergency and you close it immediately after.

Do not add these inbound rules to EC2:

```text
8003 from 0.0.0.0/0
5432 from 0.0.0.0/0
```

Reason:

- Port `8003` is the internal Gunicorn app port. Nginx will reach it inside Docker, so the public internet should not reach it directly.
- Port `5432` belongs to PostgreSQL/RDS. EC2 does not need to expose PostgreSQL publicly.

Outbound rules:

Keep the default outbound rule:

| Type | Protocol | Port | Destination | Notes |
| --- | --- | --- | --- | --- |
| All traffic | All | All | `0.0.0.0/0` | Lets EC2 install packages, pull ECR images, reach RDS, and access S3. |

RDS security group reminder:

After the EC2 security group is created, go back to the RDS security group and make sure PostgreSQL allows inbound traffic from the EC2 security group:

| Type | Protocol | Port | Source |
| --- | --- | --- | --- |
| PostgreSQL | TCP | 5432 | `rightroute-backend-prod-sg` |

Do not use `0.0.0.0/0` for the RDS PostgreSQL rule.

Storage:

```text
Root volume: 30 GB gp3 minimum
Volume type: gp3
Encryption: enabled if available
```

30 GB is enough for the first deployment because Docker images, logs, and static files will live on the server. If image builds/deployments grow, increase this to 50 GB or more. RDS stores the database separately, and S3 stores media files separately.

Advanced details:

1. Keep **termination protection** enabled if available, especially after production is live.
2. Keep the default root volume delete-on-termination behavior only if you are comfortable recreating the server from CI/CD. The important persistent data should be in RDS and S3.
3. Add useful tags:

```text
Name=rightroute-backend-prod
Project=RightRoute
Environment=Production
```

Review and launch:

1. Click **Launch instance**.
2. Wait until instance state is **Running**.
3. Wait until both status checks pass.
4. Copy the instance ID.
5. Copy the temporary public IPv4 address only for initial reference.
6. Continue to step 8 and associate a permanent Elastic IP with this instance.

---
## 8. Allocate and attach Elastic IP

AWS Console:

1. Go to **EC2 -> Elastic IPs**.
2. Allocate Elastic IP.
3. Associate it with the EC2 instance.
4. Save the Elastic IP. This is the temporary production URL.

---

## 9. Connect with Putty

From Windows:

1. Convert the `.pem` key to `.ppk` using Puttygen if needed.
2. Open Putty.
3. Host:

```text
ubuntu@YOUR_ELASTIC_IP
```

4. SSH -> Auth -> Credentials: select your `.ppk` private key.
5. Connect.

---

## 10. Prepare EC2 server

Run on EC2:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y ca-certificates curl gnupg unzip
```

Install Docker:

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker ubuntu
```

Log out and log back in so the Docker group applies.

Install AWS CLI:

```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
aws --version
```

Create app directory:

```bash
sudo mkdir -p /opt/rightroute-backend
sudo chown -R ubuntu:ubuntu /opt/rightroute-backend
cd /opt/rightroute-backend
```

---

## 11. Create production.env on EC2

On your local machine, open `production.example.env` and fill the real values.

On EC2:

```bash
nano /opt/rightroute-backend/production.env
```

Paste the filled values and save.

Important values before first deploy:

```env
SECRET_KEY=real-long-secret
DEBUG=False
ALLOWED_HOSTS=YOUR_ELASTIC_IP
CSRF_TRUSTED_ORIGINS=http://YOUR_ELASTIC_IP
USE_POSTGRES=True
POSTGRES_DB=rightroute_prod
POSTGRES_USER=rightroute_admin
POSTGRES_PASSWORD=real-rds-password
POSTGRES_HOST=your-rds-endpoint.us-east-1.rds.amazonaws.com
POSTGRES_PORT=5432
POSTGRES_SSLMODE=require
USE_S3=True
AWS_REGION=us-east-1
AWS_S3_REGION_NAME=us-east-1
AWS_STORAGE_BUCKET_NAME=rightroute-prod-media
SECURE_SSL_REDIRECT=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
```

File permissions:

```bash
chmod 600 /opt/rightroute-backend/production.env
```

---

## 12. GitHub secrets and variables

Go to GitHub repo -> **Settings -> Secrets and variables -> Actions**.

Add these **Repository secrets**:

```text
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
EC2_HOST
EC2_USER
EC2_SSH_KEY
```

Use:

```text
EC2_HOST=YOUR_ELASTIC_IP
EC2_USER=ubuntu
EC2_SSH_KEY=contents of the private key used to SSH into EC2
```

Add these **Repository variables**:

```text
AWS_REGION=us-east-1
ECR_REPOSITORY=rightroute-backend
EC2_APP_DIR=/opt/rightroute-backend
```

The AWS access key used in GitHub needs permission to push to ECR. Your current administrator key will work, but later it is better to replace it with a limited CI/CD IAM user or GitHub OIDC role.

---

## 13. First deployment

Push to `main`, or run the workflow manually from GitHub Actions:

```text
Actions -> Deploy Backend to AWS -> Run workflow
```

The workflow will:

1. Build Docker image.
2. Push image to ECR.
3. Copy `docker-compose.prod.yml` and Nginx config to EC2.
4. SSH into EC2.
5. Pull the new image.
6. Run migrations.
7. Run collectstatic.
8. Restart containers.

Check containers on EC2:

```bash
cd /opt/rightroute-backend
docker compose --env-file .deploy.env -f docker-compose.prod.yml ps
docker logs right_route_backend --tail 100
docker logs right_route_nginx --tail 100
```

Open:

```text
http://YOUR_ELASTIC_IP/
http://YOUR_ELASTIC_IP/api/docs/
```

---

## 14. Useful production commands

Restart:

```bash
cd /opt/rightroute-backend
docker compose --env-file .deploy.env -f docker-compose.prod.yml restart
```

View logs:

```bash
docker logs right_route_backend -f
docker logs right_route_nginx -f
```

Run Django shell:

```bash
cd /opt/rightroute-backend
docker compose --env-file .deploy.env -f docker-compose.prod.yml exec backend python manage.py shell
```

Create superuser:

```bash
cd /opt/rightroute-backend
docker compose --env-file .deploy.env -f docker-compose.prod.yml exec backend python manage.py createsuperuser
```

Run migrations manually:

```bash
cd /opt/rightroute-backend
docker compose --env-file .deploy.env -f docker-compose.prod.yml exec backend python manage.py migrate
```

---

## 15. Later domain and SSL setup

After domain DNS points to the Elastic IP:

1. Add an A record:

```text
api.yourdomain.com -> YOUR_ELASTIC_IP
```

2. Update `/opt/rightroute-backend/production.env`:

```env
ALLOWED_HOSTS=api.yourdomain.com,YOUR_ELASTIC_IP
CSRF_TRUSTED_ORIGINS=https://api.yourdomain.com
SITE_URL=https://api.yourdomain.com
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=False
```

3. Update `nginx/conf.d/right-route.conf` for the domain and SSL.
4. Install Certbot on EC2 or run a Certbot container.
5. Issue certificate:

```bash
sudo certbot certonly --standalone -d api.yourdomain.com
```

6. Add a renewal test:

```bash
sudo certbot renew --dry-run
```

Certbot installs a systemd timer automatically on Ubuntu packages. Verify:

```bash
systemctl list-timers | grep certbot
```

When SSL is added, port `443` must be open in the EC2 security group.
