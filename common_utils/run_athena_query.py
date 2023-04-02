import logging

import pandas as pd
from sqlalchemy.engine import create_engine
from sqlalchemy.orm import Session


class runAthenaQuery:
    def __init__(
        self,
        schema_name: str,
        s3_staging_dir: str,
        region_name: str,
        work_group: str = "primary",
    ) -> None:
        """set up the connection to athena using sqlalchemy

        Args:
            schema_name (str): schema name
            s3_staging_dir (str): s3 pathto store the queryies output
            region_name (str): aws region name
            work_group (str, optional): the athena workgroup. Defaults to 'primary'.
        """

        # Create the SQLAlchemy connection. Note that you need to have pyathena installed for this.
        engine = create_engine(
            f"""awsathena+rest://:@athena.{region_name}.amazonaws.com:443/{schema_name}?s3_staging_dir{s3_staging_dir}&work_group={work_group}"""
        )

        self.session = Session(engine, future=True)
        self.conn = engine.connect()

    def run_query_with_pandas(self, query: str) -> pd.DataFrame:
        """execute query with pandas built in method: read_sql_query()

        Args:
            query (str): the query to be executed

        Returns:
            pd.DataFrame: dataframe containing the results of the query
        """
        return pd.read_sql_query(query, self.conn)

    def run_query(
        self, query: str, get_results: bool = True, print_query: bool = False
    ) -> list:
        """execute the query in athena

        Args:
            query (str): the query to be executed
            get_results (bool, optional): whether to return the output of the query. Defaults to True.
            print_query (bool, optional): True to print it, False not. Defaults to False.

        Returns:
            list: if get_results set to True then we return the output of the query. Else, nothing is returned
        """
        if print_query:
            logging.info(f"query to be executed: {query}")

        if get_results:
            return self.session.execute(query).scalars().all()
        else:
            self.session.execute(query)
            return
