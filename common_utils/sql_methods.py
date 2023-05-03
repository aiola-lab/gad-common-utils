class sqlMethods:
    def create_athena_table_statement(
        table_name: str, columns: list[str], data_types: list[str], s3_path: str
    ) -> str:
        """
        Generates a SQL CREATE TABLE IF NOT EXISTS statement for Athena based on a list of table columns, their data types,
        and an S3 path.

        Args:
            table_name (str): The name of the table to be created.
            columns (List[str]): A list of table column names.
            data_types (List[str]): A list of data types for the table columns.
            s3_path (str): The S3 path where the data is stored.

        Returns:
            str: A SQL CREATE TABLE statement string.

        Raises:
            ValueError: If the number of columns and data types does not match.
        """
        if len(columns) != len(data_types):
            raise ValueError("Number of columns and data types does not match")

        columns_sql = ", ".join(
            [f"{col} {dtype}" for col, dtype in zip(columns, data_types)]
        )

        sql_statement = f"""CREATE EXTERNAL TABLE IF NOT EXISTS {table_name} ({columns_sql}) 
                            LOCATION '{s3_path}'
                        """
        return sql_statement
