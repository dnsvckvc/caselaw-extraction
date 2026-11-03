output "ipv4" {
  value = hcloud_server.app.ipv4_address
}

output "ipv6" {
  value = hcloud_server.app.ipv6_address
}

output "site_url" {
  value = "https://${local.fqdn.site}"
}

output "api_url" {
  value = "https://${local.fqdn.api}"
}

output "site_host" {
  value = local.fqdn.site
}

output "api_host" {
  value = local.fqdn.api
}

output "ssh" {
  value = "ssh -i ${var.ssh_public_key == "~/.ssh/caselaw-prod.pub" ? "~/.ssh/caselaw-prod" : "<private key>"} caselaw@${hcloud_server.app.ipv4_address}"
}

output "bucket" {
  value = cloudflare_r2_bucket.runs.name
}

output "r2_endpoint" {
  value = "https://${var.cloudflare_account_id}.r2.cloudflarestorage.com"
}
