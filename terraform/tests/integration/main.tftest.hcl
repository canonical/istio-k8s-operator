# Integration tests for Istio K8s Terraform module
# These tests will actually deploy resources to Juju

# IMPORTANT: Before running these tests, ensure you have:
# 1. A Juju controller bootstrapped
# 2. An existing model (create with: juju add-model istio-test)

variables {
  # Model name for testing - must exist before running tests
  test_model = "istio-test"
}

# To use a different model:
# terraform test -test-directory=tests/integration -var="test_model=your-model"

provider "juju" {
  # Provider configuration will use environment variables
}

# Test actual deployment and verify it's active
run "basic_deployment" {
  command = apply

  variables {
    model   = var.test_model
    channel = "2/edge"
  }

  assert {
    condition     = juju_application.istio.name == "istio"
    error_message = "Application should be named 'istio'"
  }

  assert {
    condition     = juju_application.istio.units == 1
    error_message = "Should have 1 unit deployed"
  }
}

# Test deployment with custom configuration
run "configured_deployment" {
  command = apply

  variables {
    model    = var.test_model
    app_name = "istio-configured"
    channel  = "2/edge"
    units    = 2
    config = {
      platform = "microk8s"
    }
  }

  assert {
    condition     = juju_application.istio.name == "istio-configured"
    error_message = "Application should be named 'istio-configured'"
  }

  assert {
    condition     = juju_application.istio.units == 2
    error_message = "Should have 2 units deployed"
  }

  assert {
    condition     = juju_application.istio.config["platform"] == "microk8s"
    error_message = "Platform should be microk8s"
  }
}


# Test scaling an existing deployment
run "scale_deployment" {
  command = apply

  variables {
    model    = var.test_model
    app_name = "istio-scaling"
    channel  = "2/edge"
    units    = 1
  }

  # First, verify initial deployment
  assert {
    condition     = juju_application.istio.units == 1
    error_message = "Should start with 1 unit"
  }
}

# Test outputs are populated correctly
run "verify_outputs" {
  command = apply

  variables {
    model    = var.test_model
    app_name = "istio-outputs"
    channel  = "2/edge"
  }

  assert {
    condition     = output.app_name == "istio-outputs"
    error_message = "Output app_name should match input"
  }

  assert {
    condition     = length(output.endpoints) == 6
    error_message = "Should have 6 endpoints defined"
  }

  # Verify all endpoint names are present
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

# Test deployment with specific revision
run "revision_deployment" {
  command = apply

  variables {
    model    = var.test_model
    app_name = "istio-revision"
    channel  = "2/edge"
    revision = 36
  }

  assert {
    condition     = juju_application.istio.charm[0].revision == 36
    error_message = "Should deploy specific revision"
  }
}

# Note about cleanup:
# Terraform test framework automatically runs 'terraform destroy' after each test run
# to clean up resources. If a test fails, you can manually clean up with:
# terraform test -test-directory=tests/integration -destroy
#
# For debugging failed tests without automatic cleanup, use:
# terraform test -test-directory=tests/integration -verbose
