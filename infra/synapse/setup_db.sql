-- Run against the reservoir database by scripts/deploy.ps1 (sqlcmd).
-- sqlcmd variables: $(STORAGE_ACCOUNT), $(ADF_NAME), $(MASTER_KEY_PASSWORD).
-- Every statement is guarded, so the script can be rerun.

IF NOT EXISTS (SELECT 1 FROM sys.symmetric_keys WHERE name = '##MS_DatabaseMasterKey##')
    CREATE MASTER KEY ENCRYPTION BY PASSWORD = '$(MASTER_KEY_PASSWORD)';
GO

-- Storage is read and written as the Synapse workspace's managed identity,
-- whoever runs the query (the factory, or a person in sqlcmd).
IF NOT EXISTS (SELECT 1 FROM sys.database_scoped_credentials WHERE name = 'workspace_identity')
    CREATE DATABASE SCOPED CREDENTIAL workspace_identity WITH IDENTITY = 'Managed Identity';
GO

IF NOT EXISTS (SELECT 1 FROM sys.external_data_sources WHERE name = 'lake')
    CREATE EXTERNAL DATA SOURCE lake WITH (
        LOCATION = 'https://$(STORAGE_ACCOUNT).dfs.core.windows.net/lake',
        CREDENTIAL = workspace_identity
    );
GO

IF NOT EXISTS (SELECT 1 FROM sys.external_file_formats WHERE name = 'parquet_snappy')
    CREATE EXTERNAL FILE FORMAT parquet_snappy WITH (
        FORMAT_TYPE = PARQUET,
        DATA_COMPRESSION = 'org.apache.hadoop.io.compress.SnappyCodec'
    );
GO

IF SCHEMA_ID('stg') IS NULL EXEC('CREATE SCHEMA stg');
GO
IF SCHEMA_ID('gold') IS NULL EXEC('CREATE SCHEMA gold');
GO

-- The factory's managed identity runs the Script and Lookup activities.
IF DATABASE_PRINCIPAL_ID('$(ADF_NAME)') IS NULL
    CREATE USER [$(ADF_NAME)] FROM EXTERNAL PROVIDER;
GO
-- CETAS needs CREATE TABLE, ALTER on the schema, and use of the data source,
-- file format and credential. db_ddladmin + db_datareader + the grants below
-- cover that without db_owner.
ALTER ROLE db_ddladmin ADD MEMBER [$(ADF_NAME)];
ALTER ROLE db_datareader ADD MEMBER [$(ADF_NAME)];
GRANT ADMINISTER DATABASE BULK OPERATIONS TO [$(ADF_NAME)];
GRANT REFERENCES ON DATABASE SCOPED CREDENTIAL::workspace_identity TO [$(ADF_NAME)];
GRANT ALTER ANY EXTERNAL DATA SOURCE TO [$(ADF_NAME)];
GRANT ALTER ANY EXTERNAL FILE FORMAT TO [$(ADF_NAME)];
GO
