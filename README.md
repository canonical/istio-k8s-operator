# Istio Service Mesh Charmed Operator

[![CharmHub Badge](https://charmhub.io/istio-k8s/badge.svg)](https://charmhub.io/istio-k8s)
[![Release](https://github.com/canonical/istio-k8s-operator/actions/workflows/release.yaml/badge.svg)](https://github.com/canonical/istio-k8s-operator/actions/workflows/release.yaml)
[![Discourse Status](https://img.shields.io/discourse/status?server=https%3A%2F%2Fdiscourse.charmhub.io&style=flat&label=CharmHub%20Discourse)](https://discourse.charmhub.io)

## Description

[Istio](https://istio.io) is an open source project that implements a service mesh, allowing for a way to observe and control the traffic flow between applications in Kubernetes.  Istio is a key tool in securing Kubernetess workloads and hardening your environment.

The istio-core Charmed Operator deploys and manages the Istio control plane components in a Kubernetes cluster.  The operator is designed to be used in conjunction with the [istio-beacon-k8s](https://github.com/canonical/istio-beacon-k8s-operator) and [istio-ingress-k8s](https://github.com/canonical/istio-ingress-k8s-operator) charms to deploy and configure Istio using Juju.

## Usage

Typically, Istio is deployed to the `istio-system` namespace without any other applications in that namespace.  This is because any Istio Custom Resource deployed to Istio's system namespace are treated as a globally scoped (for example, an `AuthorizationPolicy` deployed in Istio's namespace applies to the entire cluster).  Following these best practices, we can deploy Charmed Istio by:

```bash
juju add-model istio-system
juju deploy istio-k8s --trust
```

This deploys the Istio control plane, which can then be used by anything in the Kubernetes cluster.  To get started from here, see:
* [istio-beacon-k8s](https://github.com/canonical/istio-beacon-k8s-operator) for how to quickly integrate charms to the mesh Istio's Ambient mode
* [istio-ingress-k8s](https://github.com/canonical/istio-ingress-k8s-operator) to create ingresses to the cluster
* for general Istio guidance, see the [Istio docs](https://istio.io/latest/docs/), for example [how to deploy an application to an Istio ambient mesh](https://istio.io/latest/docs/ambient/getting-started/deploy-sample-app/)
