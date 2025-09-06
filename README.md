# Homelab Kubernetes Cluster Setup Guide

This guide outlines the steps to set up and configure your Kubernetes cluster for the homelab environment.

## 1. Node Setup (Prerequisites)

Before running the Ansible playbook, ensure your nodes meet the following prerequisites:

*   **Operating System:** A compatible Linux distribution (e.g., Ubuntu, Debian, Raspberry Pi OS).
*   **SSH Access:** SSH server installed and configured for passwordless authentication (SSH keys recommended) from your Ansible control machine.
*   **Python:** Python 3 installed on all nodes.
*   **Basic Networking:** Nodes have network connectivity and can resolve DNS.
*   **`iptables` and `open-iscsi`:** These packages are installed on all nodes. The Ansible playbook will attempt to install them, but it's good to ensure they are available.

## 2. Run Ansible Playbook (K3s & Cilium Installation)

The `install-k3s-cilium.yaml` Ansible playbook will install K3s (a lightweight Kubernetes distribution) and configure Cilium as the CNI (Container Network Interface) and Ingress controller.

**Before running:**

*   **Inventory File:** Ensure you have an Ansible inventory file (e.g., `playbooks/inventory.yaml`) that defines your master and agent nodes.
    ```yaml
    # Example playbooks/inventory.yaml
    [k3s_masters]
    control-0 ansible_host=192.168.1.210

    [k3s_agents]
    worker-1 ansible_host=199.168.1.211
    worker-2 ansible_host=199.168.1.212
    ```
    *(Replace with your actual node hostnames/IPs)*

*   **Kubeconfig User:** The playbook assumes a `kubeconfig_user` (default `pi`) for setting up kubeconfig. Adjust if necessary.

**To run the playbook:**

```bash
ansible-playbook -i playbooks/inventory.yaml playbooks/install-k3s-cilium.yaml --ask-become-pass
```
*(You may need to provide your `sudo` password for `ansible-playbook`)*

This playbook will:
*   Install necessary prerequisites (`iptables`, `open-iscsi`).
*   Install K3s on the master node and join agent nodes.
*   Install Cilium as the CNI, enabling `kubeProxyReplacement`, `l2announcements`, `externalIPs`, and `ingressController`.
*   Fetch the kubeconfig file to your local machine.

## 3. Apply Cilium Manifests (Optional, if not handled by Playbook)

If you have additional Cilium-specific configurations (e.g., `CiliumLoadBalancerIPPool`, `CiliumL2AnnouncementPolicy`) that are not part of the Ansible playbook, apply them now.

```bash
kubectl apply -f infrastructure/configs/cilium/ip-pool.yaml
kubectl apply -f infrastructure/configs/cilium/l2policy.yaml
# Add any other specific Cilium manifests here
```

## 4. Install Sealed Secrets

Sealed Secrets allows you to store encrypted Kubernetes Secrets in Git, which can then be decrypted only by the controller running in your cluster.

```bash
# Add the Bitnami Sealed Secrets Helm repository
helm repo add sealed-secrets https://bitnami-labs.github.io/sealed-secrets

# Update Helm repositories
helm repo update

# Install Sealed Secrets chart in the kube-system namespace
helm install sealed-secrets sealed-secrets/sealed-secrets -n kube-system --create-namespace

# Wait for Sealed Secrets controller to be ready
kubectl rollout status deployment/sealed-secrets -n kube-system --timeout=300s
```

## 5. Install Longhorn

Longhorn is a distributed block storage system for Kubernetes.

```bash
# Add the Longhorn Helm repository
helm repo add longhorn https://charts.longhorn.io

# Update Helm repositories
helm repo update

# Install Longhorn chart in the longhorn-system namespace
helm install longhorn longhorn/longhorn -n longhorn-system --create-namespace

# Wait for Longhorn deployment to be ready
kubectl rollout status deployment/longhorn-driver -n longhorn-system --timeout=300s
```

## 6. Resealing Secrets (e.g., for Homepage Pi-hole Password)

After a cluster re-deployment, the `sealed-secrets` controller generates a new private key. This means existing `SealedSecret` resources need to be re-encrypted with the new public key.

**Steps to Reseal a Secret:**

1.  **Fetch the current public certificate from your cluster:**
    ```bash
    kubectl get secret -n kube-system sealed-secrets-key<SUFFIX> -o jsonpath="{.data['tls\.crt']}" | base64 -d > pub-cert.pem
    ```
    *(Replace `<SUFFIX>` with the actual suffix of your `sealed-secrets-key` secret, e.g., `sealed-secrets-keyh6vzn`. You can find this by running `kubectl get secrets -n kube-system -o name | grep sealed-secrets-key`)*

2.  **Create a temporary Kubernetes Secret YAML with the plaintext value:**
    *(Replace `YOUR_PLAINTEXT_VALUE` with the actual secret value, and `SECRET_KEY_NAME` with the key name used in your secret, e.g., `PIHOLE_WEBPASSWORD`)*
    ```bash
    kubectl create secret generic <SECRET_NAME> --namespace <NAMESPACE> --from-literal=<SECRET_KEY_NAME>='YOUR_PLAINTEXT_VALUE' --dry-run=client -o yaml > /tmp/temp-secret.yaml
    ```
    *(Example for Homepage Pi-hole password: `kubectl create secret generic homepage-secret --namespace homepage --from-literal=PIHOLE_WEBPASSWORD='PASSWORD' --dry-run=client -o yaml > /tmp/homepage-secret-temp.yaml`)*

3.  **Seal the temporary Secret into a `SealedSecret`:**
    *(Replace `<SECRET_NAME>`, `<NAMESPACE>`, and `sealed-secret-file` path as appropriate)*
    ```bash
    kubeseal --cert pub-cert.pem \
             --controller-name sealed-secrets \
             --controller-namespace kube-system \
             --sealed-secret-file <PATH_TO_YOUR_SEALED_SECRET_YAML> \
             < /tmp/temp-secret.yaml
    ```
    *(Example for Homepage Pi-hole password: `kubeseal --cert /Users/kris/Dev/personal/homelab/apps/base/homepage/pub-cert.pem --controller-name sealed-secrets --controller-namespace kube-system --sealed-secret-file /Users/kris/Dev/personal/homelab/apps/base/homepage/sealed-homepage-secret.yaml < /tmp/homepage-secret-temp.yaml`)*

4.  **Apply the updated `SealedSecret` to your cluster:**
    ```bash
    kubectl apply -f <PATH_TO_YOUR_SEALED_SECRET_YAML>
    ```
    *(Example: `kubectl apply -f /Users/kris/Dev/personal/homelab/apps/base/homepage/sealed-homepage-secret.yaml`)*

5.  **Restart the affected deployment/pod:**
    ```bash
    kubectl rollout restart deployment/<YOUR_DEPLOYMENT_NAME> -n <NAMESPACE>
    ```
    *(Example: `kubectl rollout restart deployment/homepage -n homepage`)*

## 7. Accessing Longhorn Dashboard

To access the Longhorn dashboard, ensure you have applied the `longhorn-ingress.yaml` manifest:

```bash
kubectl apply -f infrastructure/longhorn/ingress.yaml
```

Then, add an entry to your local `/etc/hosts` file (or your local DNS server) to resolve `cwk.longhorn` to the IP address of your Cilium Ingress controller. You can find this IP by checking the status of the `longhorn-ingress`:

```bash
kubectl get ingress -n longhorn-system longhorn-ingress -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
```

Once resolved, navigate to `http://cwk.longhorn` in your web browser.
