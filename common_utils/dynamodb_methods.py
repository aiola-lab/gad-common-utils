import json
import logging
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key


class DataTypesEncoder(json.JSONEncoder):
    def default(self, o: any) -> any:
        """convert decimal to string and set to list

        Args:
            o (any): the itme to encode

        Returns:
            any: the item after encoding
        """
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, set):
            return list(o)
        return super(DataTypesEncoder, self).default(o)


class DynamoDbTable:
    def __init__(self, table_name: str, region: str) -> None:
        """this constructor sets the following class attributes:
        - table_name
        - ddb_table
        - ddb_table_partition_key
        - ddb_table_sort_key
        - table_keys

        Args:
            table_name (str): name of the dynamodb table
            region (str): aws region of the table
        """
        dynamo_db_resource = boto3.resource("dynamodb", region_name=region)
        self.ddb_table = dynamo_db_resource.Table(table_name)
        self.table_name = table_name

        self.ddb_table_partition_key = self.ddb_table.key_schema[0]["AttributeName"]

        try:
            self.ddb_table_sort_key = self.ddb_table.key_schema[1]["AttributeName"]
        except:
            self.ddb_table_sort_key = None

        if self.ddb_table_sort_key:
            self.table_keys = {
                "partition_key_name": self.ddb_table_partition_key,
                "sort_key_name": self.ddb_table_sort_key,
            }
        else:
            self.table_keys = {"partition_key_name": self.ddb_table_partition_key}

    def get_first_line_from_ddb(self) -> dict:
        """get the first record from the given dynamodb table. If no lines in the table an empty dict is returned

        Args:
            ddb_tbl: dynamodb table object

        Returns:
            dict: first record of the given table after json serialization
        """
        response = self.ddb_table.scan(Limit=1)
        if response["Items"]:
            regular_json_from_ddb = response["Items"][0]
            # serialize the dict to be valid json (e.g. replace set to list)
            regular_json_from_ddb_str = json.dumps(
                regular_json_from_ddb, cls=DataTypesEncoder
            )
            return json.loads(regular_json_from_ddb_str)
        else:
            return {}

    def get_specific_line_from_ddb(ddb_tbl, keys: dict) -> dict:
        """get 1 specific record from the given dynamodb table and given keys

        Args:
            ddb_tbl: dynamodb table object
            keys (dict): partition_key and sort_key (if exists) name and value

        Returns:
            dict: 1 specifc record of the given table after json serialization
        """
        response = ddb_tbl.get_item(Key=keys)
        regular_json_from_ddb = response["Item"]
        # serialize the dict to be valid json (e.g. replace set to list)
        regular_json_from_ddb_str = json.dumps(
            regular_json_from_ddb, cls=DataTypesEncoder
        )
        return json.loads(regular_json_from_ddb_str)

    @staticmethod
    def generate_update_expression(attributes_to_update: list) -> str:
        """returns an update_expression that gives alias per attribute

        Args:
            attributes_to_update (dict): the keys are the attributes to update

        Returns:
            str: update_expression to update dynamodb table with alias per attribute
        """
        temp_list = []
        # we add # to keys to avoid using reserved keywords (https://stackoverflow.com/a/74616856/7162781)
        temp_list = [f"#{k}=:_{k}" for k in attributes_to_update]
        return "set " + ", ".join(temp_list)

    @staticmethod
    def generate_expression_attribute_values(attributes_to_update: dict) -> dict:
        """returns expression_attribute_values that sets value per attribute

        Args:
            attributes_to_update (dict): the keys are the attributes to update

        Returns:
            dict: expression_attribute_values dictionary:
                    the keys are the aliases of attributes to update
                    the values are the values to set
        """
        expression_attribute_values = {}
        for k, v in attributes_to_update.items():
            expression_attribute_values[f":_{k}"] = v

        return expression_attribute_values

    @staticmethod
    def generate_expression_attribute_names(attributes_to_update: dict) -> dict:
        """returns expression_attribute_names that replaces the name of the attribute

        Args:
            attributes_to_update (dict): the keys are the attributes to update

        Returns:
            dict: the keys are the replacement and the values are the original attribute name (e.g. {'#comment': 'comment'})
        """
        return {f"#{attr}": attr for attr in attributes_to_update}

    def update_dynamodb(self, ddb_record: dict, attributes_to_update: dict) -> None:
        """update the attributes_to_update of the given record in the given dynamodb table

        Args:
            ddb_record (dict): record to update
            attributes_to_update (dict): attributes to update
        """

        ddb_table_keys = {}
        ddb_table_keys[self.ddb_table_partition_key] = ddb_record[
            self.ddb_table_partition_key
        ]
        if self.ddb_table_sort_key:
            ddb_table_keys[self.ddb_table_sort_key] = ddb_record[
                self.ddb_table_sort_key
            ]
        update_expression = DynamoDbTable.generate_update_expression(
            attributes_to_update=list(attributes_to_update.keys())
        )
        expression_attribute_values = (
            DynamoDbTable.generate_expression_attribute_values(
                attributes_to_update=attributes_to_update
            )
        )
        expression_attribute_names = DynamoDbTable.generate_expression_attribute_names(
            attributes_to_update=attributes_to_update
        )

        # update the record in dynamodb
        response = self.ddb_table.update_item(
            Key=ddb_table_keys,
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_attribute_values,
            ExpressionAttributeNames=expression_attribute_names,
            ReturnValues="UPDATED_NEW",
        )

        logging.info(
            f"the following attributes were updated in the table {self.ddb_table}: {response['Attributes']}"
        )

    def get_all_table_rows(self) -> list:
        """get all rows of the given dynamodb table

        Args:
            table (dynamodb table object): table to get the rows from

        Returns:
            list: all table rows
        """
        response = self.ddb_table.scan()
        rows = response["Items"]
        while "LastEvaluatedKey" in response:
            response = self.ddb_table.scan(
                ExclusiveStartKey=response["LastEvaluatedKey"]
            )
            rows.extend(response["Items"])
        return rows

    def get_specific_row(
        self,
        partition_key_value: str,
        sort_key_value: str,
    ) -> dict:
        """get a specifc row of a dynamodb table by its keys

        Args:
            table (dynamodb table object): table to get the row from
            partition_key_col_name (str): partition key name of the table
            partition_key_value (str): partition key value of a specific row
            sort_key_col_name (str): sort key name of the table
            sort_key_value (str): sort key value of a specific row

        Returns:
            dict: 1 dynamodb record
        """
        return self.ddb_table.query(
            KeyConditionExpression=Key(self.ddb_table_partition_key).eq(
                partition_key_value
            )
            & Key(self.ddb_table_sort_key).eq(sort_key_value)
        )["Items"]
