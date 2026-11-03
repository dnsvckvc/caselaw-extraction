variable "project" {
  type    = string
  default = "caselaw"
}

variable "location" {
  description = "Hetzner location: nbg1 Nuremberg, fsn1 Falkenstein, hel1 Helsinki."
  type        = string
  default     = "nbg1"
}

variable "server_type" {
  description = "Hetzner server type. The 2 vCPU / 4 GB shared Intel type; `hcloud server-type list` shows what the project offers."
  type        = string
  default     = "cx23"
}

variable "image" {
  type    = string
  default = "ubuntu-24.04"
}

variable "ssh_public_key" {
  description = "Public key that may log in as `caselaw` (and as root for recovery)."
  type        = string
  default     = "~/.ssh/caselaw-prod.pub"
}

variable "domain" {
  description = "Zone at Njalla."
  type        = string
  default     = "inat.io"
}

variable "site_host" {
  description = "Record name of the static site (report, graph), relative to the zone."
  type        = string
  default     = "caselaw"
}

variable "api_host" {
  description = "Record name of the API, relative to the zone."
  type        = string
  default     = "api.caselaw"
}

variable "dns_ttl" {
  type    = number
  default = 300
}

variable "bucket" {
  description = "R2 bucket for the run Parquet and the database dumps."
  type        = string
  default     = "caselaw-runs"
}

variable "cloudflare_account_id" {
  type = string
}

variable "njalla_api_token" {
  type      = string
  sensitive = true
}
