import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from awsglue.context import GlueContext
from awsglue.job import Job
from pyspark.context import SparkContext
from pyspark.sql import Window
from pyspark.sql.functions import lit, col, when, expr, to_date, date_format, year, dayofmonth, floor, row_number, hour
from pyspark.sql.types import IntegerType
from awsglue.dynamicframe import DynamicFrame

# Initialize Glue context
args = getResolvedOptions(sys.argv, ['JOB_NAME'])
sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

# Fetch data from Glue Data Catalog using DynamicDataFrame
master_dyf = glueContext.create_dynamic_frame.from_catalog(
    database="git-db",
    table_name="nyc_merged_raw_data"
)
zone_dyf = glueContext.create_dynamic_frame.from_catalog(
    database="git-db",
    table_name="zone_table"
)

# Convert DynamicDataFrames to Spark DataFrames for transformations
master_df = master_dyf.toDF()
zone_df = zone_dyf.toDF()

# Data transformations
transformed_df = (master_df
    # Filter out null & zero passenger_count and null & 99 RatecodeID
    .filter((col("passenger_count").isNotNull()) & (col("passenger_count") != 0))
    .filter((col("RatecodeID").isNotNull()) & (col("RatecodeID") != 99))

    # Drop unused columns
    .drop("store_and_fwd_flag", "airport_fee", "congestion_surcharge")
    
    # Cast timestamp
    .withColumn("tpep_pickup_datetime", col("tpep_pickup_datetime").cast("timestamp"))
    
    # Add week of month
    .withColumn("week_of_month", (floor((dayofmonth("tpep_pickup_datetime") - 1) / 7) + 1).cast("int"))
    
    # Add day name
    .withColumn("day_name", date_format("tpep_pickup_datetime", "EEEE"))
    
    # Add time of day
    .withColumn("time_of_day",
                when((hour(col("tpep_pickup_datetime")) >= 6) & (hour(col("tpep_pickup_datetime")) < 18), "Day")
                .otherwise("Night"))
    
    # Cast types
    .withColumn("passenger_count", col("passenger_count").cast(IntegerType()))
    .withColumn("RatecodeID", col("RatecodeID").cast(IntegerType()))
    
    # Join with zone lookup tables
    .join(zone_df.select(col("LocationID").alias("PULocationID"),
                        col("Zone").alias("pickup_zone"),
                        col("Borough").alias("pickup_borough")),
          on="PULocationID", how="left")
    .join(zone_df.select(col("LocationID").alias("DOLocationID"),
                        col("Zone").alias("dropoff_zone"),
                        col("Borough").alias("dropoff_borough")),
          on="DOLocationID", how="left")
    
    # Add row number as Id
    .withColumn("Id", row_number().over(Window.orderBy(lit(1))))
    
    # Add tip percentage
    .withColumn("tip_percentage",
                when(col("fare_amount") > 0, (col("tip_amount") / col("fare_amount")) * 100)
                .otherwise(0))
    
    # Filter extreme values
    .filter((col("trip_distance") <= 100) & (col("fare_amount") <= 500))
    
    # Add distance bucket
    .withColumn("distance_bucket",
                when(col("trip_distance") < 1, "0-1 miles")
                .when((col("trip_distance") >= 1) & (col("trip_distance") < 5), "1-5 miles")
                .when((col("trip_distance") >= 5) & (col("trip_distance") < 10), "5-10 miles")
                .otherwise("10+ miles"))
    
    # Map payment type
    .withColumn("payment_type_desc",
                expr("""
                    CASE payment_type
                        WHEN 1 THEN 'Credit Card'
                        WHEN 2 THEN 'Cash'
                        WHEN 3 THEN 'No Charge'
                        WHEN 4 THEN 'Dispute'
                        WHEN 5 THEN 'Unknown'
                        WHEN 6 THEN 'Voided'
                        ELSE 'Other'
                    END
                """))
    
    # Map RatecodeID
    .withColumn("ratecode_desc",
                when(col("RatecodeID") == 1, "Standard rate")
                .when(col("RatecodeID") == 2, "JFK")
                .when(col("RatecodeID") == 3, "Newark")
                .when(col("RatecodeID") == 4, "Nassau or Westchester")
                .when(col("RatecodeID") == 5, "Negotiated fare")
                .when(col("RatecodeID") == 6, "Group ride")
                .otherwise("Other"))
    
    # Map VendorID
    .withColumn("vendor_desc",
                when(col("VendorID") == 1, "Creative Mobile Technologies, LLC")
                .when(col("VendorID") == 2, "Curb Mobility, LLC")
                .when(col("VendorID") == 6, "Myle Technologies Inc")
                .when(col("VendorID") == 7, "Helix")
                .when(col("VendorID").isin(3, 4, 5), "Third Party"))
    
    # Drop unnecessary columns
    .drop("service_zone")
)

# Write transformed data to clean data bucket
transformed_df.write.mode("overwrite").partitionBy("year").parquet("s3://git-warehouse-bck/clean-data/")

# Commit the job
job.commit()