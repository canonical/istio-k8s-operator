# Istio Service Mesh Charmed Operator

[![CharmHub Badge](https://charmhub.io/istio-k8s/badge.svg)](https://charmhub.io/istio-k8s)
[![Release](https://github.com/canonical/istio-k8s-operator/actions/workflows/release.yaml/badge.svg)](https://github.com/canonical/istio-k8s-operator/actions/workflows/release.yaml)
[![Discourse Status](https://img.shields.io/discourse/status?server=https%3A%2F%2Fdiscourse.charmhub.io&style=flat&label=CharmHub%20Discourse)](https://discourse.charmhub.io)

## Description

[Istio](https://istio.io) is an open source project that implements a service mesh, allowing for a way to observe and control the traffic flow between applications in Kubernetes.  Istio is a key tool in securing Kubernetess workloads and hardening your environment.

The istio-core Charmed Operator deploys and manages the Istio control plane components in a Kubernetes cluster.  The operator is designed to be used in conjunction with the [istio-beacon-k8s](https://github.com/canonical/istio-beacon-operator) and [istio-ingress-k8s](https://github.com/canonical/istio-beacon-operator) charms to deploy and configure Istio using Juju.
