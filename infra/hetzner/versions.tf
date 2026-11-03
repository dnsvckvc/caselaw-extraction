terraform {
  required_version = ">= 1.6"
  required_providers {
    hcloud     = { source = "hetznercloud/hcloud", version = ">= 1.50" }
    cloudflare = { source = "cloudflare/cloudflare", version = ">= 5.0" }
    njalla     = { source = "Sighery/njalla", version = ">= 0.10" }
  }
}

# HCLOUD_TOKEN and CLOUDFLARE_API_TOKEN come from the environment; `op run` injects them from
# 1Password (terraform.op.env). Njalla's provider takes the token as an attribute, fed by the
# TF_VAR_njalla_api_token variable from the same file.
provider "hcloud" {}
provider "cloudflare" {}
provider "njalla" {
  api_token = var.njalla_api_token
}
