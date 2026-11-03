# Case-law extraction API on one Hetzner server (week 4, chosen over the AWS stack in
# ../terraform for cost: about EUR 4.50 instead of USD 47 per month). Terraform provides the
# server with its firewall and SSH key, the R2 bucket, and the two DNS records at Njalla.
# Everything on the server (Postgres, the API, Caddy, the Grafana agent, the backup cron) is
# Docker Compose, installed by cloud-init and deployed with scripts/hz.sh.

locals {
  name = var.project
  fqdn = {
    site = "${var.site_host}.${var.domain}"
    api  = "${var.api_host}.${var.domain}"
  }
}

resource "hcloud_ssh_key" "admin" {
  name       = "${local.name}-admin"
  public_key = file(pathexpand(var.ssh_public_key))
}

resource "hcloud_firewall" "web" {
  name = "${local.name}-web"

  rule {
    description = "ssh"
    direction   = "in"
    protocol    = "tcp"
    port        = "22"
    source_ips  = ["0.0.0.0/0", "::/0"]
  }
  rule {
    description = "http (Let's Encrypt challenge, redirect)"
    direction   = "in"
    protocol    = "tcp"
    port        = "80"
    source_ips  = ["0.0.0.0/0", "::/0"]
  }
  rule {
    description = "https"
    direction   = "in"
    protocol    = "tcp"
    port        = "443"
    source_ips  = ["0.0.0.0/0", "::/0"]
  }
  rule {
    description = "ping"
    direction   = "in"
    protocol    = "icmp"
    source_ips  = ["0.0.0.0/0", "::/0"]
  }
}

resource "hcloud_server" "app" {
  name         = local.name
  server_type  = var.server_type
  image        = var.image
  location     = var.location
  ssh_keys     = [hcloud_ssh_key.admin.id]
  firewall_ids = [hcloud_firewall.web.id]
  user_data = templatefile("${path.module}/cloud-init.yaml", {
    ssh_public_key = trimspace(file(pathexpand(var.ssh_public_key)))
    site_host      = local.fqdn.site
    api_host       = local.fqdn.api
  })
  labels = { project = local.name }

  public_net {
    ipv4_enabled = true
    ipv6_enabled = true
  }

  lifecycle {
    ignore_changes = [user_data] # cloud-init runs once; a changed script must not recreate the server
  }
}

resource "cloudflare_r2_bucket" "runs" {
  account_id = var.cloudflare_account_id
  name       = var.bucket
  location   = "WEUR"
}

resource "njalla_record_a" "site" {
  domain  = var.domain
  name    = var.site_host
  content = hcloud_server.app.ipv4_address
  ttl     = var.dns_ttl
}

resource "njalla_record_a" "api" {
  domain  = var.domain
  name    = var.api_host
  content = hcloud_server.app.ipv4_address
  ttl     = var.dns_ttl
}
