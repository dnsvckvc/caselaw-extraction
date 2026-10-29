# The run tables (decisions, spans, citations, centrality as Parquet, plus run.json) under
# s3://<bucket>/runs/<run_id>/. `make aws-sync` uploads a local run; the loader task reads it.
resource "aws_s3_bucket" "runs" {
  bucket        = local.bucket
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "runs" {
  bucket                  = aws_s3_bucket.runs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "runs" {
  bucket = aws_s3_bucket.runs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
