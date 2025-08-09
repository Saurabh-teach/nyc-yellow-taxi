# Configure the AWS provider with the specified region
provider "aws" {
  region = var.aws_region
}

###############################################
# AWS Glue Job for Data Transformation
###############################################
resource "aws_glue_job" "transform_job" {
  name     = "nyc-transform-job"                   # Glue job name
  role_arn = var.iam_role                          # IAM role ARN

  # Job command and script settings
  command {
    name            = "glueetl"                    # Job type (glueetl = Spark ETL)
    script_location = var.glue_script_s3_path      # S3 path to transformation script
    python_version  = "3"                          # Use Python 3
  }

  default_arguments = {
    "--job-bookmark-option"                   = "job-bookmark-disable"
    "--enable-metrics"                        = "true"
    "--enable-continuous-cloudwatch-log"      = "true"
    "--enable-spark-ui"                       = "true"
  }

  # Retry and timeout configurations
  max_retries = 0                                   # Retry once if the job fails
  timeout     = 120                                 # Timeout in minutes
  glue_version = "5.0"                              # Glue runtime version

  # Optional: Specify number of workers and type
  number_of_workers = 2                             # Number of DPUs
  worker_type       = "G.1X"                        # Worker type (G.1X or G.2X)

  # Optional: Job description
  description = "ETL job to transform NYC Yellow Taxi data"
}

###############################################
# AWS Glue Crawler for Source Data
###############################################
resource "aws_glue_crawler" "source_crawler" {
  name          = "nyc-source-crawler"              # Unique name of the source crawler
  role          = var.iam_role                      # IAM role used by the crawler
  database_name = var.raw_glue_database             # Glue database to store source data catalog

  # Define the S3 data sources for crawling raw data and lookup CSV
  s3_target {
    path = "s3://datalake-grp-03/nyc-merged-raw-data/" # S3 path to raw data (adjusted to folder)
  }
  s3_target {
    path = "s3://datalake-grp-03/zone-table/taxi_zone_lookup.csv" # S3 path to lookup CSV
  }
}

###############################################
# AWS Glue Crawler for Transformed Data
###############################################
resource "aws_glue_crawler" "transformed_data_crawler" {
  name          = "nyc-transformed-crawler"          # Unique name of the transformed data crawler
  role          = var.iam_role                      # IAM role used by the crawler
  database_name = var.transformed_glue_database     # Glue database to store transformed data catalog

  # Define the S3 data source for crawling transformed data
  s3_target {
    path = "s3://git-warehouse-bck/clean-data/"     # S3 path to transformed data
  }

  depends_on = [aws_glue_job.transform_job]
}