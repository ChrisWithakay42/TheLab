# Homelab Kubernetes Cluster

This repository is dedicated to my journey of learning and applying platform engineering skills and best practices. Self-hosting applications provides an invaluable, hands-on experience, forcing me to consider the entire application lifecycle—from initial configuration to end-user access. This includes crucial considerations for backups and disaster recovery, security hardening, and designing for scalability where needed.

## Hardware

The Kubernetes cluster runs on a heterogeneous mix of nodes, blending low-power ARM-based devices with more powerful x86 hardware. This setup provides a realistic environment for managing diverse architectures.

**Bare Metal Nodes:**
*   3 x Raspberry Pi 5 (8GB RAM)
*   1 x HP EliteDesk G4 Desktop Mini (64GB RAM)

**Virtualised Nodes:**
*   Failover VMs are hosted on a separate Proxmox cluster, providing resilience. A detailed look into the Proxmox setup will be available in another repository in the near future.

## Cluster Provisioning and Architecture

All nodes run hardened Ubuntu Server, with configurations following security best practices outlined by Canonical and the Cloud Native Computing Foundation (CNCF).

To ensure consistency and rapid deployment, the cluster provisioning process is automated using Ansible playbooks. These playbooks handle everything from initial setup to node configuration, making it easy to tear down, rebuild, or scale the cluster by adding or removing nodes.

## Hosted Applications

The cluster hosts a variety of applications, separated into infrastructure management, end-user services, and custom-built projects.

### Infrastructure Management

These applications form the backbone of the cluster, providing essential services for storage, secrets management, and observability.

| Application                 | Description                                                                                             |
| --------------------------- | ------------------------------------------------------------------------------------------------------- |
| **Longhorn**                | Provides persistent, replicated block storage for stateful applications.                                |
| **HashiCorp Vault**         | Manages secrets, ensuring that sensitive information is stored securely and accessed via authentication.  |
| **External Secrets Operator** | Syncs secrets from Vault into Kubernetes `Secret` objects, making them available to applications.       |
| **pgAdmin**                 | A web-based GUI for managing PostgreSQL databases running in the cluster.                               |
| **Prometheus**              | Collects and stores time-series metrics from nodes and applications for system monitoring.              |
| **Grafana**                 | Visualizes metrics from Prometheus, providing dashboards for observability and system health.           |
| **Graylog**                 | A centralized log management solution for security monitoring and application debugging.                |

### GitOps

Currently, the GitOps workflow is centered around GitLab Runners, which handle CI/CD pipelines for deploying applications. There is a future intent to migrate this workflow to Flux for a more declarative, pull-based GitOps approach.

### End-User Applications

These applications provide services directly to users on the local network.

| Application   | Description                                                                                             |
| ------------- | ------------------------------------------------------------------------------------------------------- |
| **Homepage**  | A custom, web-based portal that serves as a central dashboard for accessing all homelab services.         |
| **Pi-hole**   | Provides network-wide ad-blocking and local DNS management.                                             |
| **Ollama**    | Hosts and serves smaller Large Language Models (LLMs) for various AI-powered tasks.                     |
| **Open WebUI**| An intuitive web interface for interacting with the LLMs hosted on Ollama.                                |

### Custom-Built Applications

These are projects I have developed to solve specific needs or explore new technologies.

| Application                       | Description                                                                                                                                 |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **Blog**                          | A personal blog built with Hugo, a fast and modern static site generator.                                                                   |
| **Utility Consumption Dashboard** | A custom dashboard built with Go and HTMX that consumes data from provider smart meter APIs to visualize utility usage and costs.           |
| **Financial Tracking System**   | A personal finance tracker that integrates with the self-hosted Ollama models for intelligent data analysis and categorization. |
