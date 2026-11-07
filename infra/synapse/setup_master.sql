-- Run against the serverless endpoint's master database by scripts/deploy.ps1.
-- UTF-8 binary collation: CDEC text is ASCII, comparisons are exact and
-- case-sensitive (same as DuckDB), and Parquet strings need no conversion.
IF DB_ID('reservoir') IS NULL
    CREATE DATABASE reservoir COLLATE Latin1_General_100_BIN2_UTF8;
GO
