# TraceWorth staging infrastructure

This directory is a **deployment proposal implemented as Terraform**, not an
already deployed environment. Read [the staging guide](../docs/staging-setup.md)
before applying it. Local validation cannot prove AWS permissions, service
quotas, routing, availability, or the final bill.

- `bootstrap/`: a protected, versioned S3 bucket for Terraform state.
- `staging/`: the private pilot environment in us-east-2 with a generated
  CloudFront hostname. The website remains a separate future deployment.
- `.terraform.lock.hcl`: commit provider checksums so reviews and CI use the
  same provider version. Do not commit `.terraform/`, state, plans or real tfvars.

The configuration uses an internal ALB and a CloudFront VPC origin. Only the
AWS-managed VPC-origin security group can reach the ALB. API caching is disabled;
the API receives authorization, cookies, Origin and CSRF headers. A static-only
rewrite handles SPA navigation without replacing API errors with index.html.

RDS is private, encrypted, Single-AZ, with seven-day backups and deletion
protection. The runtime secret and bootstrap secret are empty containers until
an operator adds values outside Terraform. The API never receives the RDS master
secret. A separate one-off task performs schema/admin work.

CloudFront WAF requires explicit pilot IPv4 egress CIDRs, with a per-IP rate
limit. This is a restricted pilot, not public beta onboarding. WAF limits are
approximate and do not replace tenant quotas or application delivery diagnostics.

## Offline checks

From the repository root, with Terraform on PATH:

```powershell
terraform fmt -check -recursive infra
terraform -chdir=infra/bootstrap init -backend=false
terraform -chdir=infra/bootstrap validate
terraform -chdir=infra/staging init -backend=false
terraform -chdir=infra/staging validate
```

`init -backend=false` downloads providers but does not connect to state or create
AWS resources. Provider downloads require internet access. A real plan uses AWS
read APIs; an apply changes AWS resources. Never treat validate as a deployment
test.

## Design limits to review before apply

- One NAT gateway and Single-AZ RDS accept staging outages. NAT, ALB, RDS, WAF,
  Fargate, public IPv4, Secrets Manager, logs and traffic contribute to cost.
- Viewer connections use HTTPS. The private CloudFront-to-ALB and ALB-to-task
  hops use HTTP; this is not end-to-end TLS. PostgreSQL verifies RDS TLS.
- Confirm `10.42.0.0/16` does not overlap any network you plan to connect.
- The initial `container_image = null` / `api_desired_count = 0` prevents starting
  an unprepared API, but **does not stop the other resources from billing** after
  apply. Prepare a tested image locally before any staging apply.
- No secret values are Terraform inputs. Use Secrets Manager and do not pass
  passwords in shell arguments, ECS overrides or saved plans.
- CloudWatch alarms require confirming the SNS subscription email. Missing
  metrics are not treated as failures during initial bootstrap; these alarms
  alone do not detect a completely absent service. Add an external HTTPS probe
  and verify alert delivery at deployment acceptance.
- Telemetry retention is an explicit backend administrative command; schedule
  and verify it before sustained traffic. Terraform does not yet schedule it.
- A default private pilot allowlist requires predictable outbound IPv4 addresses.
  A Lambda outside a VPC usually does not have a stable egress IP; resolve that
  networking decision before integrating MyHandyAI.

References: [AWS VPC origins](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-vpc-origins.html),
[Terraform S3 state and locking](https://developer.hashicorp.com/terraform/language/backend/s3),
[CloudFront authorization forwarding](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/http-401-unauthorized.html).
