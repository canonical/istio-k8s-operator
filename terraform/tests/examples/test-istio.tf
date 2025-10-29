terraform {
  required_version = ">= 1.5"
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "~> 1.0"
    }
  }
}

provider "juju" {
  # These values can be set through environment variables:
  # JUJU_CONTROLLER_ADDRESSES - controller endpoint
  # JUJU_USERNAME - username
  # JUJU_PASSWORD - password
  # JUJU_CA_CERT - CA certificate

  # Or you can specify them explicitly:
  # controller_addresses = "10.0.0.1:17070"
  # username = "admin"
  # password = "your-password"
  # ca_certificate = file("~/juju-ca-cert.crt")
}

# Create a model for testing
resource "juju_model" "istio_test" {
  name = "istio-test"

  # Specify your cloud/substrate
  # For example, for microk8s:
  # cloud {
  #   name = "microk8s"
  # }

  # For other Kubernetes clouds, adjust accordingly
}

# Deploy Istio using the module
module "istio" {
  source = "../.."

  # Required: reference to the model
  model_uuid = juju_model.istio_test.uuid

  # Optional: customize the deployment
  app_name = "istio"
  channel  = "2/edge" # or specify a specific channel
  units    = 1

  # Optional: charm configuration
  config = {
    # Enable ambient mode (default is true)
    ambient = true

    # Platform-specific settings (e.g., for MicroK8s)
    # platform = "microk8s"

    # Auto-allow waypoint policy
    # auto-allow-waypoint-policy = true
  }

  # Optional: constraints
  constraints = "arch=amd64"
}

# Outputs to verify deployment
output "istio_app_name" {
  value = module.istio.app_name
}

output "istio_endpoints" {
  value = module.istio.endpoints
}
