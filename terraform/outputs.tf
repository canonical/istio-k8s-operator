output "app_name" {
  value = juju_application.istio.name
}

output "provides" {
  value = {
    grafana_dashboard = "grafana-dashboard"
    istio_metadata    = "istio-metadata"
    metrics_endpoint  = "metrics-endpoint"
  }
}

output "requires" {
  value = {
    charm_tracing        = "charm-tracing"
    workload_tracing     = "workload-tracing"
    istio_ingress_config = "istio-ingress-config"
  }
}
