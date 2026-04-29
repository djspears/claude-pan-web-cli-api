# AKS Deployment YAMLs

This directory contains Kubernetes manifest files for deploying the Claude + PAN AIRS proxy to Azure Kubernetes Service (AKS).

## Prerequisites

- Azure CLI installed and authenticated (`az login`)
- kubectl installed and configured for your AKS cluster
- Docker Hub images already pushed:
  - `<your-username>/claude-pan-web-cli-api:latest`
  - `<your-username>/claude-pan-web-cli-api:v1.0.0`

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

Edit `deployment.yaml` and replace `YOUR_DOCKER_USERNAME` with your Docker Hub username on line 23:

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

### 4. Deploy to AKS

Connect to your AKS cluster:

```bash
az aks get-credentials --resource-group <your-rg> --name <your-cluster>
```

Apply all manifests:

```bash
kubectl apply -f aks-kubectl-yamls/
```

Or apply them individually in order:

```bash
kubectl apply -f aks-kubectl-yamls/namespace.yaml
kubectl apply -f aks-kubectl-yamls/secret.yaml
kubectl apply -f aks-kubectl-yamls/configmap.yaml
kubectl apply -f aks-kubectl-yamls/deployment.yaml
kubectl apply -f aks-kubectl-yamls/service.yaml
```

### 5. Get the External IP

Wait for the LoadBalancer to provision an external IP:

```bash
kubectl get svc -n claude-pan-airs -w
```

Once you see an IP in the `EXTERNAL-IP` column, access the application:

```
http://<EXTERNAL-IP>/
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
curl http://<EXTERNAL-IP>/health
```

## Update Deployment

To update the image version:

```bash
kubectl set image deployment/claude-pan-proxy \
  claude-pan-proxy=<your-username>/claude-pan-web-cli-api:v1.0.0 \
  -n claude-pan-airs
```

Or edit `deployment.yaml` and reapply:

```bash
kubectl apply -f aks-kubectl-yamls/deployment.yaml
```

## Scaling

Scale the number of replicas:

```bash
kubectl scale deployment/claude-pan-proxy --replicas=3 -n claude-pan-airs
```

## Cleanup

Delete all resources:

```bash
kubectl delete -f aks-kubectl-yamls/
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
| `service.yaml` | LoadBalancer service exposing port 80 |

## Troubleshooting

**Pods not starting:**
```bash
kubectl describe pod -n claude-pan-airs -l app=claude-pan-proxy
kubectl logs -n claude-pan-airs -l app=claude-pan-proxy
```

**Service has no external IP:**
- Wait a few minutes for Azure to provision the LoadBalancer
- Check AKS networking configuration
- Verify your AKS cluster has access to create LoadBalancers

**API errors:**
- Verify secrets are correctly set: `kubectl get secret claude-pan-secrets -n claude-pan-airs -o yaml`
- Check logs for API authentication errors
- Test the /health endpoint to see PAN and Claude status
