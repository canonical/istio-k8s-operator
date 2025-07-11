# Test configuration for Istio K8s Terraform module

variables {
  test_model_name = "istio-test-model"
}

provider "juju" {
  # Provider configuration will use environment variables in CI
}

# Test default deployment
run "default_deployment" {
  command = plan

  variables {
    model   = var.test_model_name
    channel = "2/edge"
  }

  assert {
    condition     = juju_application.istio.name == "istio"
    error_message = "Default application name should be 'istio'"
  }

  assert {
    condition     = juju_application.istio.units == 1
    error_message = "Default units should be 1"
  }

  assert {
    condition     = juju_application.istio.trust == true
    error_message = "Trust should be enabled for Kubernetes permissions"
  }

  assert {
    condition     = juju_application.istio.constraints == "arch=amd64"
    error_message = "Default constraints should be 'arch=amd64'"
  }
}

# Test custom application name
run "custom_app_name" {
  command = plan

  variables {
    model    = var.test_model_name
    app_name = "my-istio"
    channel  = "2/edge"
  }

  assert {
    condition     = juju_application.istio.name == "my-istio"
    error_message = "Application name should be 'my-istio'"
  }
}

# Test scaling configuration
run "scaled_deployment" {
  command = plan

  variables {
    model   = var.test_model_name
    channel = "2/edge"
    units   = 3
  }

  assert {
    condition     = juju_application.istio.units == 3
    error_message = "Units should be 3"
  }
}

# Test channel configuration
run "channel_configuration" {
  command = plan

  variables {
    model   = var.test_model_name
    channel = "2/stable"
  }

  assert {
    condition     = juju_application.istio.charm[0].channel == "2/stable"
    error_message = "Channel should be '2/stable'"
  }
}

# Test revision configuration
run "revision_configuration" {
  command = plan

  variables {
    model    = var.test_model_name
    channel  = "2/edge"
    revision = 42
  }

  assert {
    condition     = juju_application.istio.charm[0].revision == 42
    error_message = "Revision should be 42"
  }
}

# Test charm configuration
run "charm_config" {
  command = plan

  variables {
    model   = var.test_model_name
    channel = "2/edge"
    config = {
      ambient                    = false
      auto-allow-waypoint-policy = true
      platform                   = "microk8s"
    }
  }

  assert {
    condition     = juju_application.istio.config["ambient"] == "false"
    error_message = "Ambient should be disabled in config"
  }

  assert {
    condition     = juju_application.istio.config["auto-allow-waypoint-policy"] == "true"
    error_message = "Auto-allow-waypoint-policy should be enabled"
  }

  assert {
    condition     = juju_application.istio.config["platform"] == "microk8s"
    error_message = "Platform should be 'microk8s'"
  }
}

# Test custom constraints
run "custom_constraints" {
  command = plan

  variables {
    model       = var.test_model_name
    channel     = "2/edge"
    constraints = "arch=arm64 cores=4 mem=8G"
  }

  assert {
    condition     = juju_application.istio.constraints == "arch=arm64 cores=4 mem=8G"
    error_message = "Constraints should match the custom value"
  }
}

# Test storage directives
run "storage_directives" {
  command = plan

  variables {
    model   = var.test_model_name
    channel = "2/edge"
    storage_directives = {
      data = "ebs,10G"
    }
  }

  assert {
    condition     = juju_application.istio.storage_directives["data"] == "ebs,10G"
    error_message = "Storage directive for 'data' should be 'ebs,10G'"
  }
}

# Test outputs
run "output_values" {
  command = plan

  variables {
    model    = var.test_model_name
    app_name = "test-istio"
    channel  = "2/edge"
  }

  assert {
    condition     = output.app_name == "test-istio"
    error_message = "Output app_name should match the input"
  }

  assert {
    condition     = length(output.endpoints) == 6
    error_message = "Should have 6 endpoints (3 requires, 3 provides)"
  }

  assert {
    condition     = output.endpoints.charm_tracing == "charm-tracing"
    error_message = "Should have charm-tracing endpoint"
  }

  assert {
    condition     = output.endpoints.workload_tracing == "workload-tracing"
    error_message = "Should have workload-tracing endpoint"
  }

  assert {
    condition     = output.endpoints.istio_ingress_config == "istio-ingress-config"
    error_message = "Should have istio-ingress-config endpoint"
  }

  assert {
    condition     = output.endpoints.grafana_dashboard == "grafana-dashboard"
    error_message = "Should have grafana-dashboard endpoint"
  }

  assert {
    condition     = output.endpoints.istio_metadata == "istio-metadata"
    error_message = "Should have istio-metadata endpoint"
  }

  assert {
    condition     = output.endpoints.metrics_endpoint == "metrics-endpoint"
    error_message = "Should have metrics-endpoint endpoint"
  }
}

# Test empty config
run "empty_config" {
  command = plan

  variables {
    model   = var.test_model_name
    channel = "2/edge"
    config  = {}
  }

  # Should succeed without errors - config is optional
  assert {
    condition     = juju_application.istio.name == "istio"
    error_message = "Should deploy successfully with empty config"
  }
}

# Test model reference
run "model_reference" {
  command = plan

  variables {
    model   = "different-model"
    channel = "2/edge"
  }

  assert {
    condition     = juju_application.istio.model == "different-model"
    error_message = "Model should be 'different-model'"
  }
}
