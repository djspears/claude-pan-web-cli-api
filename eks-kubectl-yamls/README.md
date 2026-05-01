# EKS Deployment YAMLs

This directory contains Kubernetes manifest files for deploying the Claude + PAN AIRS proxy to Amazon Elastic Kubernetes Service (EKS).

## Prerequisites

- AWS CLI installed and authenticated (`aws configure`)
- kubectl installed and configured for your EKS cluster
- eksctl (optional, for cluster management)
- Docker Hub images already pushed:
  - `<your-username>/claude-pan-web-cli-api:latest`
  - `<your-username>/claude-pan-web-cli-api:v1.1.0`

## Quick Start

### 1. Configure Your Secrets

Copy the secret template and add your credentials:

```bash
cp secret.yaml.template secret.yaml
```

Edit `secret.yaml` and replace the placeholders:
- `YOUR_ANTHROPIC_API_KEY_HERE` - Your Anthropic API key (starts with `sk-ant-`)
- `YOUR_PAN_API_KEY_HERE` - Your PAN AIRS API key
- `YOUR_PROFILE_NAME_HERE` - Your PAN AIRS profile name
- `YOUR_PROFILE_ID_HERE` - Your PAN AIRS profile ID (UUID)

**IMPORTANT**: `secret.yaml` is git-ignored. Never commit it!

### 2. Update Docker Image Reference

Edit `deployment.yaml` and replace `YOUR_DOCKER_USERNAME` with your Docker Hub username on line 26:

```yaml
image: YOUR_DOCKER_USERNAME/claude-pan-web-cli-api:latest
```

For example:
```yaml
image: djspears/claude-pan-web-cli-api:latest
```

### 3. (Optional) Customize Configuration

Edit `configmap.yaml` if you need to change:
- `PAN_API_URL` - PAN AIRS API endpoint
- `PAN_APP_NAME` - Application name sent to PAN
- `CLAUDE_MODEL` - Claude model to use
- `LOG_LEVEL` - Logging verbosity

### 4. (Optional) Customize Load Balancer

Edit `service.yaml` annotations to configure AWS Load Balancer:

```yaml
# Use Network Load Balancer (default, recommended for performance)
service.beta.kubernetes.io/aws-load-balancer-type: "nlb"

# Or use Application Load Balancer (requires AWS Load Balancer Controller)
service.beta.kubernetes.io/aws-load-balancer-type: "external"

# For internal-only access (no public IP)
service.beta.kubernetes.io/aws-load-balancer-scheme: "internal"

# For HTTPS with ACM certificate
service.beta.kubernetes.io/aws-load-balancer-ssl-cert: "arn:aws:acm:region:account:certificate/cert-id"
service.beta.kubernetes.io/aws-load-balancer-ssl-ports: "443"
```

### 5. Deploy to EKS

Connect to your EKS cluster:

```bash
aws eks update-kubeconfig --region <your-region> --name <your-cluster>
```

Apply all manifests:

```bash
kubectl apply -f eks-kubectl-yamls/
```

Or apply them individually in order:

```bash
kubectl apply -f eks-kubectl-yamls/namespace.yaml
kubectl apply -f eks-kubectl-yamls/secret.yaml
kubectl apply -f eks-kubectl-yamls/configmap.yaml
kubectl apply -f eks-kubectl-yamls/deployment.yaml
kubectl apply -f eks-kubectl-yamls/service.yaml
```

### 6. Get the External URL

Wait for the LoadBalancer to provision an external hostname:

```bash
kubectl get svc -n claude-pan-airs -w
```

Once you see a hostname in the `EXTERNAL-IP` column (e.g., `a1b2c3...elb.amazonaws.com`), access the application:

```bash
# Get the Load Balancer hostname
LB_HOST=$(kubectl get svc claude-pan-proxy -n claude-pan-airs -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
echo "Application URL: http://$LB_HOST"

# Test it
curl http://$LB_HOST/health
```

## Verify Deployment

Check pod status:

```bash
kubectl get pods -n claude-pan-airs
```

Check pod logs:

```bash
kubectl logs -n claude-pan-airs -l app=claude-pan-proxy --tail=50 -f
```

Check health endpoint:

```bash
LB_HOST=$(kubectl get svc claude-pan-proxy -n claude-pan-airs -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
curl http://$LB_HOST/health | jq .
```

## Update Deployment

To update the image version:

```bash
kubectl set image deployment/claude-pan-proxy \
  claude-pan-proxy=<your-username>/claude-pan-web-cli-api:v1.1.0 \
  -n claude-pan-airs
```

Or edit `deployment.yaml` and reapply:

```bash
kubectl apply -f eks-kubectl-yamls/deployment.yaml
```

## Scaling

Scale the number of replicas:

```bash
kubectl scale deployment/claude-pan-proxy --replicas=3 -n claude-pan-airs
```

## Toggling AIRS On/Off

To disable AIRS scanning (useful for testing Claude's native guardrails):

```bash
kubectl edit configmap claude-pan-config -n claude-pan-airs
# Change PAN_ENABLED: "false"
kubectl rollout restart deployment/claude-pan-proxy -n claude-pan-airs
```

To re-enable:

```bash
kubectl edit configmap claude-pan-config -n claude-pan-airs
# Change PAN_ENABLED: "true"
kubectl rollout restart deployment/claude-pan-proxy -n claude-pan-airs
```

Verify:

```bash
LB_HOST=$(kubectl get svc claude-pan-proxy -n claude-pan-airs -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
curl http://$LB_HOST/health | jq '.pan_status'
# Returns: "disabled" or "connected"
```

## Cleanup

Delete all resources:

```bash
kubectl delete -f eks-kubectl-yamls/
```

Or delete just the namespace (removes everything):

```bash
kubectl delete namespace claude-pan-airs
```

## Files Overview

| File | Description |
|------|-------------|
| `namespace.yaml` | Creates the `claude-pan-airs` namespace |
| `secret.yaml.template` | Template for API keys (copy to `secret.yaml`) |
| `configmap.yaml` | Application configuration (non-sensitive) |
| `deployment.yaml` | Deployment with 2 replicas, health probes, resource limits |
| `service.yaml` | LoadBalancer service with AWS-specific annotations |

## EKS-Specific Notes

### Load Balancer Types

**Network Load Balancer (NLB)** - Default, recommended
- Faster, Layer 4 load balancing
- Lower latency
- Source IP preservation
- Fixed IP addresses per AZ

```yaml
service.beta.kubernetes.io/aws-load-balancer-type: "nlb"
```

**Application Load Balancer (ALB)** - Requires AWS Load Balancer Controller
- Layer 7 load balancing
- Better for HTTP/HTTPS routing
- Path-based routing
- WAF integration

```yaml
service.beta.kubernetes.io/aws-load-balancer-type: "external"
```

To use ALB, install the AWS Load Balancer Controller:
```bash
eksctl utils associate-iam-oidc-provider --cluster=<cluster-name> --approve

kubectl apply -k "github.com/aws/eks-charts/stable/aws-load-balancer-controller//crds?ref=master"

helm repo add eks https://aws.github.io/eks-charts
helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=<cluster-name>
```

### HTTPS/SSL with ACM

To enable HTTPS with AWS Certificate Manager:

1. **Create ACM certificate** for your domain
2. **Update service.yaml** annotations:

```yaml
service.beta.kubernetes.io/aws-load-balancer-ssl-cert: "arn:aws:acm:us-east-1:123456789:certificate/abc-123"
service.beta.kubernetes.io/aws-load-balancer-ssl-ports: "443"
service.beta.kubernetes.io/aws-load-balancer-backend-protocol: "http"
```

3. **Update port configuration:**

```yaml
ports:
- port: 443
  targetPort: 8080
  protocol: TCP
  name: https
```

### Internal Load Balancer (Private)

For internal-only access (no public IP):

```yaml
service.beta.kubernetes.io/aws-load-balancer-scheme: "internal"
```

### Cross-Zone Load Balancing

Enable traffic distribution across all availability zones:

```yaml
service.beta.kubernetes.io/aws-load-balancer-cross-zone-load-balancing-enabled: "true"
```

### Security Groups

To specify custom security groups:

```yaml
service.beta.kubernetes.io/aws-load-balancer-security-groups: "sg-123456,sg-789012"
```

### IAM Roles for Service Accounts (IRSA)

If your application needs AWS API access (not required for this app):

```bash
eksctl create iamserviceaccount \
  --name claude-pan-proxy \
  --namespace claude-pan-airs \
  --cluster <cluster-name> \
  --attach-policy-arn arn:aws:iam::aws:policy/YourPolicy \
  --approve
```

## Troubleshooting

**Pods not starting:**
```bash
kubectl describe pod -n claude-pan-airs -l app=claude-pan-proxy
kubectl logs -n claude-pan-airs -l app=claude-pan-proxy
```

**Service has no external hostname:**
- Wait a few minutes for AWS to provision the LoadBalancer
- Check EKS cluster IAM permissions for ELB creation
- Verify VPC and subnet configuration

**LoadBalancer timeout:**
- Check security groups allow traffic on port 80
- Verify EKS worker nodes are in public subnets (for internet-facing LB)
- Check pod health with `kubectl get pods`

**API errors:**
- Verify secrets are correctly set: `kubectl get secret claude-pan-secrets -n claude-pan-airs -o yaml`
- Check logs for API authentication errors
- Test the /health endpoint to see PAN and Claude status

**DNS resolution:**
- EKS Load Balancers provide hostnames, not IP addresses
- Use the hostname directly or create a CNAME record in Route 53
