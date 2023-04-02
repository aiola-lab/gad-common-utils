import logging
from datetime import datetime, timedelta

import awswrangler as wr


class dateTimeMethods:
    def get_timestamp(timestamp_string: str) -> datetime:
        """
        Returns a timestamp object from a given timestamp string.

        The timestamp string can be in the format 'YYYY-MM-DD' (date) or 'YYYY-MM-DD HH:MM:SS' (datetime).

        Args:
            timestamp_string (str): The timestamp string to be parsed.

        Returns:
            datetime: The timestamp object.

        Raises:
            ValueError: If the timestamp string is in an invalid format.
        """

        if not isinstance(timestamp_string, str):
            raise ValueError("timestamp_string should be string")
        formats = ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S"]
        for f in formats:
            try:
                return datetime.strptime(timestamp_string, f)
            except ValueError:
                pass
        raise ValueError(f"Invalid timestamp string. Should be one of {formats}")

    def get_max_timestamp_from_athena(
        col_name: str,
        tbl_name: str,
        database: str,
        workgroup: str,
        default_from_timestamp: str = "2022-01-01",
        reduce_10_seconds: bool = True,
    ) -> datetime:
        """
        Queries Athena database for the maximum timestamp in a specified table, and returns the timestamp minus 10 seconds.
        If the table doesn't exist - the default from_timestamp is returned
        If the schema doesn't exist - we create it AND the default from_timestamp is returned

        Args:

        col_name (str): the name of the column to get the max timestamp from
        tbl_name (str): the name of the table in the Athena database
        database (str): the name of the Athena database
        workgroup (str): the name of the Athena workgroup to use for the query
        default_from_timestamp (str): the default timestmap to use if the table is empty / doens't exist
        Returns:

        datetime: the maximum timestamp from the specified table, minus 10 seconds OR the default from_timestamp
        """

        logging.info(f"get the max timestamp from {tbl_name}")
        try:
            df = wr.athena.read_sql_query(
                sql=f"""select coalesce(max({col_name}), timestamp'{default_from_timestamp}') as max_timestamp from {tbl_name}""",
                database=database,
                workgroup=workgroup,
            )

            max_timestamp = df["max_timestamp"][0]

        except Exception as e:
            if "does not exist" in str(e):
                if "Table" in str(e):
                    logging.warning(
                        f"the table/view {database}.{tbl_name} doesn't exist"
                    )
                elif "Schema" in str(e):
                    logging.warning(
                        f"the schema {database} doesn't exists. Creating it now..."
                    )
                    wr.athena.start_query_execution(f"create database {database}")
                    logging.info(f"schema {database} was created")
                else:
                    logging.warning(
                        f"the query to get max timestamp from {database}.{tbl_name} failed with this error message: {e}"
                    )
            else:
                logging.warning(
                    f"the query to get max timestamp from {database}.{tbl_name} failed with this error message: {e}"
                )

            logging.info(
                "from_timestamp will be assigned with default value to fetch all data"
            )
            max_timestamp = default_from_timestamp

        # we reduce 10 seconds to make sure we don't miss any rows
        if reduce_10_seconds:
            return max_timestamp - timedelta(seconds=10)
        else:
            return max_timestamp
