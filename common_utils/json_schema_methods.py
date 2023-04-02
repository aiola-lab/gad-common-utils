import copy
import logging

from jsonschema import ValidationError, validate


class JsonSchemaMethods:
    def custom_validate(_data: dict, _schema: dict) -> dict:
        """this method gets a json object and schema and checks if the json object fits the schema.
        - we use the validate function provided by the jsonschema module
        - if a missing key is found by the validate function it throws an exception (mentioning only the first missing key)
        - once we get this exception, we add the missing key to the json and set the value as defined in the given schema
        - we keep checking until the json match the schema
        - once there are no missing keys in the json, we return it

        if the schema is not valid - an exception is thrown
        if there is a type mismatch - an exception is thrown

        Args:
            _data (dict): the json object to validate
            _schema (dict): the schema

        Raises:
            e: the schema is not valid
            e: different data type
            e: other exception

        Returns:
            dict: the json object with all keys (according to the schema)
        """

        # deepcopy makes sure we won't change the original values we have in the record we get
        _data_copy = copy.deepcopy(_data)
        while True:
            try:
                validate(_data_copy, _schema)
                break
            except ValidationError as e:
                if "error_msg" in e.schema:
                    logging.error(e.schema["error_msg"])
                    raise e

                # the schema is valid, check the data
                else:
                    # missing key
                    if e.validator == "required":
                        missing_property = e.message.split(" ")[0].replace("'", "")
                        logging.warning(
                            f"{'.'.join(str(p) for p in e.path)}.{missing_property} property is missing"
                        )

                        # add nested missing property and set default value
                        if e.path:
                            path_to_missing_property = list(e.path)
                            # create a pointer to the location where the property is missing (in the json object to validate)
                            _missing_property_pointer = (
                                JsonSchemaMethods.get_key_value_by_given_path(
                                    input_dict=_data_copy,
                                    keys=path_to_missing_property,
                                    as_pointer=True,
                                )
                            )

                            # assign the default value of the nested missing property to the pointer of
                            # the json object (since it's a pointer, this will change the json object as well)
                            _missing_property_pointer[
                                missing_property
                            ] = JsonSchemaMethods.get_default_value_of_given_property(
                                schema=_schema,
                                property_name=missing_property,
                                property_path=path_to_missing_property,
                            )
                        # add NON nested missing property (first level in the schema) and set default value
                        else:
                            _data_copy[
                                missing_property
                            ] = JsonSchemaMethods.get_default_value_of_given_property(
                                schema=_schema,
                                property_name=missing_property,
                                property_path=[missing_property],
                            )

                    # different data type
                    elif e.validator == "type":
                        logging.critical(
                            f"the data type of {e.json_path} property is different between "
                            "the source and the target. Please check"
                        )
                        raise e
                    # other kind of failure
                    else:
                        raise e
        return _data_copy

    def get_key_value_by_given_path(
        input_dict: dict, keys: list, as_pointer: bool = False
    ) -> any:
        """
        Get the value of a dictionary attribute specified by a list of keys, either as a pointer or a deep copy.

        Args:
        - input_dict (dict): The input dictionary.
        - keys (list): A list of keys specifying the path to the desired dictionary attribute.
        - as_pointer (bool): If True, returns a pointer to the desired dictionary attribute. If False, returns a deep copy.

        Returns:
        - Any: The value of the desired dictionary attribute.
        """
        if as_pointer:
            dict_to_use = input_dict
        else:
            dict_to_use = copy.deepcopy(input_dict)

        for key in keys:
            dict_to_use = dict_to_use[key]

        return dict_to_use

    def get_default_value_of_given_property(
        schema: dict, property_name: str, property_path: list
    ) -> any:
        """
        Get the default value of a specified property in a JSON schema.

        Args:
        - schema (dict): The input JSON schema.
        - property_name (str): The name of the property to get the default value for.
        - property_path (list): A list of keys specifying the path to the desired property in the JSON schema.

        Returns:
        - Any: The default value of the specified property in the JSON schema.
        """
        path_to_property = [
            "properties",
            property_path[0],
            "default",
        ]

        # for nested properties
        if len(property_path) > 1:
            for p in property_path[1:]:
                path_to_property.append(p)

            path_to_property.append(property_name)

        return JsonSchemaMethods.get_key_value_by_given_path(
            input_dict=schema, keys=path_to_property
        )
