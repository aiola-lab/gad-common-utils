import ast
import logging
import os
from datetime import datetime

import awswrangler as wr
import boto3
from dateutil.relativedelta import relativedelta

from common_utils.date_time_methods import dateTimeMethods


class dataLoadingManagement:
    """
    Class to manage data loading operations. It provides functions to set the start and end timestamps for the data loading,
    validating the start and end timestamps, and creating the schema if the data is being loaded for the first time.

    Args:
        from_timestamp: A string, representing the start timestamp specified by the user.
        to_timestamp: A string, representing the end timestamp specified by the user.
        full_load: A string, indicating whether the data is being loaded for the first time.
        full_load_from_timestamp: A string, representing the start timestamp to use if the data is being loaded for the first time and the start timestamp is specified by the user.
        full_load_from_timestamp_months_back: An integer, representing the number of months to
            go back to calculate the default start timestamp if the data is being loaded for the first time and the start timestamp is not specified by the user.
        athena_workgroup: A string, representing the name of the Athena workgroup to use.
        timestamp_col_name: A string, representing the name of the column in the source data which contains the timestamp.
        tbl_to_check_max_timestamp: A string, representing the name of the table in the destination database to check for the max timestamp.
        from_and_to_as_dates: A boolean, indicating whether the start and end timestamps should be set as dates (midnight of the given date).
        create_schema_if_full_load: A boolean, indicating whether the schema should be created if the data is being loaded for the first time.
    """

    def __init__(
        self,
        from_timestamp: str = None,
        to_timestamp: str = None,
        full_load: bool = False,
        full_load_from_timestamp: str = None,
        full_load_from_timestamp_months_back: int = 3,
        athena_workgroup: str = "primary",
        timestamp_col_name: str = None,
        tbl_to_check_max_timestamp: str = None,
        from_and_to_as_dates: bool = False,
        create_schema_if_full_load: bool = True,
    ):
        """
        Initializes the class and sets the start and end timestamps, and creates the schema if the data is being loaded for the first time.
        """
        self.given_from_timestamp = from_timestamp
        self.given_to_timestamp = to_timestamp
        self.full_load = ast.literal_eval(full_load)
        self.full_load_from_timestamp = full_load_from_timestamp
        self.full_load_from_timestamp_months_back = full_load_from_timestamp_months_back

        self.dest_schema = os.environ.get("ATHENA_DB")
        self.athena_workgroup = athena_workgroup
        self.timestamp_col_name = timestamp_col_name
        self.tbl_to_check_max_timestamp = tbl_to_check_max_timestamp

        # to be used if nothing else is given
        self.default_from_timestamp = (
            datetime.now()
            - relativedelta(months=self.full_load_from_timestamp_months_back)
        ).replace(microsecond=0)

        self.from_timestamp = None
        self.to_timestamp = None

        # we define the session here so that it can be used by all the functions
        boto3.setup_default_session(region_name=os.environ.get("REGION"))

        self.set_from_and_to_timestamps(as_dates=from_and_to_as_dates)

        if create_schema_if_full_load:
            self.create_schema_if_not_exists()

    def set_from_and_to_timestamps(self, as_dates: bool = False):
        """
        Sets the start and end timestamps for the data loading based on the user-specified timestamps and default values.

        Args:
            as_dates: A boolean, indicating whether the start and end timestamps should be set as dates (midnight of the given date).

        Returns:
            None
        """
        # set from/to_timestamp to fetch all data when the table is recrated
        if self.full_load:
            self.set_from_timestamp_full_load()

            self.to_timestamp = datetime.now()
        else:
            self.set_from_timestamp_partial_load()

            if self.given_to_timestamp:
                self.to_timestamp = dateTimeMethods.get_timestamp(
                    self.given_to_timestamp
                )
            else:
                self.to_timestamp = datetime.now()

        # set the from and to timestamps as midnight of the given date
        if as_dates:
            self.from_timestamp = self.from_timestamp.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            self.to_timestamp = self.to_timestamp.replace(
                hour=0, minute=0, second=0, microsecond=0
            )

        self.validate_from_and_to_timestamp()

    def set_from_timestamp_full_load(self):
        """Sets the from_timestamp for full load.

        If `full_load_from_timestamp` is given, it is used as the `from_timestamp`.
        If not, the `from_timestamp` is calculated as `full_load_from_timestamp_months_back` months back from today.
        The information about the process is logged.

        Returns:
            None
        """
        logging.info(
            "full_load is True, so from_timestamp and to_timestamp will be assigned with default values to fetch all data"
        )
        if self.full_load_from_timestamp:
            logging.info(
                f"full_load_from_timestamp is given and will be used as the from_timestamp: {self.full_load_from_timestamp}"
            )
            self.from_timestamp = dateTimeMethods.get_timestamp(
                self.full_load_from_timestamp
            )
        else:
            self.from_timestamp = self.default_from_timestamp
            logging.info(
                f"full_load_from_timestamp was NOT given, from_timestamp will be {self.full_load_from_timestamp_months_back} month back from today: {self.from_timestamp}"
            )

    def set_from_timestamp_partial_load(self):
        """Sets the from_timestamp for partial load.

        If `given_from_timestamp` is given, it is used as the `from_timestamp`.
        If not, the `from_timestamp` is calculated as the maximum timestamp in the `tbl_to_check_max_timestamp` table in the Athena database.
        The default value is set if it can't be retrieved from the table.

        Returns:
            None
        """
        if self.given_from_timestamp:
            self.from_timestamp = dateTimeMethods.get_timestamp(
                self.given_from_timestamp
            )
        else:
            self.from_timestamp = dateTimeMethods.get_max_timestamp_from_athena(
                col_name=self.timestamp_col_name,
                tbl_name=self.tbl_to_check_max_timestamp,
                database=self.dest_schema,
                workgroup=self.athena_workgroup,
                default_from_timestamp=self.default_from_timestamp,
                reduce_10_seconds=False,
            )

    def validate_from_and_to_timestamp(self):
        """
        Validate the from and to timestamps to make sure that the to_timestamp is not smaller than the from_timestamp.
        Log a warning if the to_timestamp is smaller, and log an info message if the validation is successful.

        Returns:
            None
        """
        if self.to_timestamp < self.from_timestamp:
            logging.warning(
                "to_timestamp is bigger than the from_timestamp. no data to fetch"
            )
        else:
            logging.info(
                f"fetching data from: {self.from_timestamp} until: {self.to_timestamp}"
            )

    def create_schema_if_not_exists(self):
        """
        Check if the "full_load" attribute is set to True and create the destination schema if it doesn't exist yet.

        Returns:
            None
        """
        if self.full_load:
            logging.info(
                f"full load is True. the schema {self.dest_schema} will be created if not exist yet"
            )
            wr.athena.start_query_execution(
                f"create database if not exists {self.dest_schema}"
            )
