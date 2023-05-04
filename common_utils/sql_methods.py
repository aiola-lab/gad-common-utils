class sqlMethods:
    def create_athena_table_statement(
        table_name: str,
        col_types: dict[str, str],
        s3_path: str,
        partition_cols: list[str] = [],
    ) -> str:
        """
        Generates a SQL CREATE TABLE IF NOT EXISTS statement for Athena based on a dictionary of table columns and their data
        types, and an S3 path.

        Args:
            table_name (str): The name of the table to be created.
            col_types (Dict[str, str]): A dictionary of table column names and their corresponding data types.
            s3_path (str): The S3 path where the data is stored.

        Returns:
            str: A SQL CREATE TABLE statement string.
        """

        # Exclude partition columns from the list of columns
        columns = [col for col in col_types.keys() if col not in partition_cols]
        columns_sql = ", ".join([f"{col} {col_types[col]}" for col in columns])

        partition_cols_sql = ", ".join(
            [f"{col} {col_types[col]}" for col in partition_cols]
        )
        partition_clause = (
            f"PARTITIONED BY ({partition_cols_sql})" if partition_cols_sql else ""
        )

        sql_statement = f"""
                            CREATE EXTERNAL TABLE IF NOT EXISTS {table_name} ({columns_sql}) 
                            {partition_clause}
                            LOCATION '{s3_path}'
                        """
        return sql_statement
