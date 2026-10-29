variable "region" {
  description = "AWS region. Frankfurt is the closest region to Switzerland with every service used here."
  type        = string
  default     = "eu-central-1"
}

variable "project" {
  description = "Name prefix of every resource."
  type        = string
  default     = "caselaw"
}

variable "run_id" {
  description = "Extraction run the API serves (a run_id loaded into the database)."
  type        = string
  default     = "regex-v0.4"
}

variable "image_tag" {
  description = "Tag of the API image in ECR that the task definitions reference."
  type        = string
  default     = "latest"
}

variable "api_cpu" {
  description = "Fargate CPU units of the API task (256 = 0.25 vCPU)."
  type        = number
  default     = 256
}

variable "api_memory" {
  description = "Fargate memory of the API task in MiB."
  type        = number
  default     = 512
}

variable "api_desired_count" {
  description = "Running API tasks. Set 0 on the first apply, before an image exists in ECR."
  type        = number
  default     = 1
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "db_allocated_storage" {
  description = "RDS storage in GiB (the two local runs take 256 MB)."
  type        = number
  default     = 20
}

variable "db_publicly_accessible" {
  description = "Give the database a public address (with db_allowed_cidrs) to load it from a laptop instead of the Fargate loader task."
  type        = bool
  default     = false
}

variable "db_allowed_cidrs" {
  description = "CIDR blocks allowed to reach Postgres besides the API tasks, e.g. [\"203.0.113.4/32\"]."
  type        = list(string)
  default     = []
}

variable "alarm_email" {
  description = "E-mail address for the alarm topic. Empty = no subscription (alarms still show in the console)."
  type        = string
  default     = ""
}

variable "github_repo" {
  description = "`owner/name` of the GitHub repository allowed to deploy through OIDC. Empty = no deploy role."
  type        = string
  default     = ""
}
