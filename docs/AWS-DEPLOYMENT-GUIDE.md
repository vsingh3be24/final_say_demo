# FinalSay AWS deployment readiness

No AWS deployment has been performed from this checkout. The ECS files are
templates; they require an operator-owned AWS account, managed database,
domain, secrets, and IAM configuration before deployment.
The local Docker CLI is present but its daemon is unavailable, and the AWS CLI
is not installed in this environment.

The production template uses the semantic model, managed PostgreSQL, AWS
Secrets Manager, GitHub Actions OIDC, and a health check that verifies database
connectivity. `FINALSAY_ENVIRONMENT=production` makes application startup reject
SQLite, the built-in development JWT secret or secrets shorter than 32
characters, and wildcard or non-HTTPS CORS origins. It does not seed demo users
or synthetic notices.

## Production prerequisites

- Managed PostgreSQL in private subnets, automated backups, and a tested
  restore procedure.
- Separate AWS Secrets Manager secrets for the PostgreSQL SQLAlchemy URL and
  a random JWT secret of at least 32 characters.
- An ECS task execution role with ECR pull, CloudWatch Logs write, and
  `secretsmanager:GetSecretValue` permissions restricted to those secret ARNs.
- A GitHub OIDC deploy role trusted only for this repository and the `main`
  branch, with minimum ECR push and ECS update permissions.
- An HTTPS load balancer and the exact production frontend origin for CORS.
  Keep tasks in private subnets; allow ECS port 8000 only from the load
  balancer.
- Outbound HTTPS from private ECS tasks to the selected official notice
  portals, typically through a NAT gateway. The image build downloads the
  configured model weights from Hugging Face; runtime inference is set to use
  those cached artifacts offline.

## ECS deployment setup

1. Create a private ECR repository named `finalsay-backend`, an ECS cluster,
   CloudWatch log group `/ecs/finalsay-backend`, a managed PostgreSQL database,
   an HTTPS load balancer, and private task subnets.

2. Store the database URL and JWT secret in separate AWS Secrets Manager
   secrets. Give the ECS task execution role access to exactly those secrets.
   The database URL should use the PostgreSQL driver installed by the backend,
   for example `postgresql+psycopg2://...`.

3. Configure GitHub repository variables:

   - `AWS_ROLE_ARN`
   - `ECS_TASK_EXECUTION_ROLE_ARN`
   - `FINALSAY_DATABASE_URL_SECRET_ARN`
   - `FINALSAY_JWT_SECRET_ARN`
   - `FINALSAY_CORS_ORIGINS` (the exact HTTPS frontend origin)

   The GitHub Actions workflow assumes `AWS_ROLE_ARN` through OIDC; it does not
   need long-lived AWS access keys. The deployment fails before task rendering
   if any required variable is missing.

4. Configure security groups so only the HTTPS load balancer can reach ECS on
   port 8000, and only ECS tasks can reach PostgreSQL. Do not expose ECS port
   8000 or the database publicly.

5. The deployment workflow builds and pushes an immutable SHA-tagged image,
   renders the secret references and CORS origin into the task definition, and
   waits for ECS service stability. Deploy a reviewed backend change to `main`
   or run the workflow manually after every prerequisite is configured.

6. Verify the load-balancer URL at `/api/health/ready`, inspect ECS task logs,
   then test student, issuer, reviewer, and source-poll workflows against the
   production database before opening access to users.

Source polling uses a PostgreSQL session advisory lock shared across API
tasks. Keep the database connection available for the full poll; monitor
`scrape_run` status and task logs for coordination failures. Local tests mock
the PostgreSQL lock behavior, so verify contention and lock release against
the managed database in a pre-production environment before scaling ECS beyond
one task.

The task definition sets `FINALSAY_COMPARISON_MODEL=semantic` and the local
provenance anchor. It makes no claim of Polygon deployment. A funded wallet,
contract address, and confirmed receipt remain separate prerequisites if
public-chain anchoring is required.

## Local image validation

The local Docker CLI is installed, but the daemon socket is unavailable.
Docker Desktop is present; Launch Services reports `kLSNoExecutableErr` when
opening its app bundle, and directly starting its nested executable exits with
status 134. The image build remains unverified. On a host with working Docker
access, build the image before AWS configuration:

```bash
docker build -t finalsay-backend:check -f Dockerfile .
```

The Dockerfile downloads the configured semantic embedding and NLI weights
into the image cache and sets Hugging Face offline flags for runtime. The
first GitHub Actions build must confirm model download, ownership, image size,
and ECS task startup. The build runner needs HTTPS access to Hugging Face,
while the running ECS task needs outbound access to official notice portals
for scheduled polling.
